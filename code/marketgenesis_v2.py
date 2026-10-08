from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reproduced"

# Prefer a bundled font when present, then common CJK fonts on macOS,
# Windows and Linux.  Numeric outputs remain valid even if no CJK font exists.
FONT_REGULAR_CANDIDATES = (
    ROOT / "fonts" / "NotoSansCJKsc-Regular.otf",
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
)
FONT_BOLD_CANDIDATES = (
    ROOT / "fonts" / "NotoSansCJKsc-Bold.otf",
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
)

NAVY = "#102D49"
BLUE = "#1D649C"
RED = "#B82A30"
GOLD = "#A77623"
GREEN = "#39735C"
GRAY = "#66717D"
LIGHT = "#F5F7F9"
GRID = "#DCE3E8"


@dataclass(frozen=True)
class ExperimentConfig:
    n_pre: int = 240
    n_post: int = 120
    shock_steps: int = 5
    doses: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 4.0)
    n_replicates: int = 320
    noise_sigma: float = 0.00032
    fundamental_reversion: float = 0.055
    quiet_momentum: float = 0.035
    shock_flow_per_step: float = 0.24
    price_impact: float = 0.0125
    root_seed: int = 20260830
    bootstrap_draws: int = 2500
    abc_bank_size: int = 700
    abc_accept_fraction: float = 0.10
    abc_probe_dose: float = 1.5
    abc_probe_horizon: int = 18
    abc_holdout_doses: tuple[float, ...] = (2.0, 4.0)
    abc_holdout_horizon: int = 30
    abc_holdout_seed_offset: int = 99_999


@dataclass(frozen=True)
class WorldParameters:
    name: str
    leverage: float
    latent_inventory: float
    margin_buffer: float
    liquidation_base: float
    liquidation_gain: float
    crowding: float
    liquidity_withdrawal: float
    liquidity_inventory_sensitivity: float


STABLE = WorldParameters(
    name="stable",
    leverage=1.8,
    latent_inventory=0.42,
    margin_buffer=0.052,
    liquidation_base=0.018,
    liquidation_gain=2.2,
    crowding=0.45,
    liquidity_withdrawal=4.0,
    liquidity_inventory_sensitivity=0.18,
)

FRAGILE = WorldParameters(
    name="fragile",
    leverage=5.8,
    latent_inventory=0.90,
    margin_buffer=0.019,
    liquidation_base=0.035,
    liquidation_gain=5.0,
    crowding=0.75,
    liquidity_withdrawal=6.0,
    liquidity_inventory_sensitivity=0.28,
)

ABC_TRUTH = WorldParameters(
    name="abc_truth",
    leverage=5.2,
    latent_inventory=0.82,
    margin_buffer=0.021,
    liquidation_base=0.032,
    liquidation_gain=4.5,
    crowding=0.68,
    liquidity_withdrawal=5.4,
    liquidity_inventory_sensitivity=0.24,
)


OBSERVABLE_COLUMNS = (
    "price",
    "log_return",
    "volume_index",
    "spread_bps",
    "depth",
    "order_imbalance",
)


# The 700 candidate worlds are draws from one declared eight-dimensional
# parameter box, all evaluated by the same simulator equations.
CANDIDATE_BANK_SEED_OFFSET = 77_777
CANDIDATE_PARAMETER_RANGES = {
    "leverage": (1.3, 7.0),
    "latent_inventory": (0.30, 1.10),
    "margin_buffer": (0.016, 0.060),
    "liquidation_base": (0.012, 0.052),
    "liquidation_gain": (1.5, 6.5),
    "crowding": (0.25, 1.10),
    "liquidity_withdrawal": (2.5, 8.5),
    "liquidity_inventory_sensitivity": (0.08, 0.38),
}
CANDIDATE_PARAMETER_NAMES = tuple(CANDIDATE_PARAMETER_RANGES)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = FONT_BOLD_CANDIDATES if bold else FONT_REGULAR_CANDIDATES
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def common_innovations(config: ExperimentConfig, seed: int) -> np.ndarray:
    """Generate bounded innovations so the quiet regime stays below every margin buffer."""

    rng = np.random.default_rng(seed)
    total = config.n_pre + config.n_post
    noise = rng.normal(0.0, config.noise_sigma, size=total)
    return np.clip(noise, -3.0 * config.noise_sigma, 3.0 * config.noise_sigma)


def simulate_market(
    parameters: WorldParameters,
    innovations: np.ndarray,
    config: ExperimentConfig,
    dose: float,
) -> pd.DataFrame:
    """Run one partially observed market under one common set of equations.

    The world label is never consulted. Structural parameters enter only through
    generic margin, liquidation, crowding and liquidity equations. Before any
    constraint is active, different hidden structures therefore have exactly
    the same observables. An external meta-order is a treatment, not a scripted
    world-specific crash.
    """

    total = config.n_pre + config.n_post
    if len(innovations) != total:
        raise ValueError(f"Expected {total} innovations, got {len(innovations)}")
    if dose < 0.0:
        raise ValueError("Dose must be non-negative")

    log_fundamental = math.log(100.0)
    log_price = np.empty(total + 1, dtype=float)
    log_return = np.zeros(total + 1, dtype=float)
    volume = np.ones(total + 1, dtype=float)
    spread = np.full(total + 1, 4.0, dtype=float)
    depth = np.ones(total + 1, dtype=float)
    imbalance = np.zeros(total + 1, dtype=float)
    stress = np.zeros(total + 1, dtype=float)
    forced_flow = np.zeros(total + 1, dtype=float)
    shock_flow = np.zeros(total + 1, dtype=float)
    liquidation_inventory = np.full(total + 1, parameters.latent_inventory, dtype=float)
    hidden_leverage = np.full(total + 1, parameters.leverage, dtype=float)

    log_price[0] = log_fundamental
    running_peak = log_price[0]

    for t in range(1, total + 1):
        previous_price = log_price[t - 1]
        previous_return = log_return[t - 1]
        inventory_before = liquidation_inventory[t - 1]
        drawdown_before = max(0.0, running_peak - previous_price)
        margin_shortfall = max(0.0, drawdown_before - parameters.margin_buffer)

        # This is the same activation rule for every candidate world. Differences
        # emerge only because their latent parameters and inventories differ.
        activation = float(margin_shortfall > 0.0)
        fraction = activation * (
            parameters.liquidation_base + parameters.liquidation_gain * margin_shortfall
        )
        liquidated = min(inventory_before, fraction * inventory_before)
        endogenous_flow = -parameters.crowding * parameters.leverage * liquidated

        inventory_after = max(0.0, inventory_before - liquidated)
        inventory_used = 1.0 - inventory_after / max(parameters.latent_inventory, 1e-12)
        current_depth = max(
            0.20,
            1.0
            - parameters.liquidity_withdrawal * margin_shortfall
            - parameters.liquidity_inventory_sensitivity * inventory_used,
        )

        treatment_active = config.n_pre <= t < config.n_pre + config.shock_steps
        external_flow = -dose * config.shock_flow_per_step if treatment_active else 0.0
        base_return = (
            config.fundamental_reversion * (log_fundamental - previous_price)
            + config.quiet_momentum * previous_return
            + float(innovations[t - 1])
        )
        flow_return = config.price_impact * (external_flow + endogenous_flow) / current_depth
        step_return = float(np.clip(base_return + flow_return, -0.12, 0.08))

        log_price[t] = previous_price + step_return
        log_return[t] = step_return
        running_peak = max(running_peak, log_price[t])
        stress[t] = margin_shortfall
        forced_flow[t] = endogenous_flow
        shock_flow[t] = external_flow
        depth[t] = current_depth
        liquidation_inventory[t] = inventory_after
        hidden_leverage[t] = 1.0 + (parameters.leverage - 1.0) * (
            inventory_after / max(parameters.latent_inventory, 1e-12)
        )

        total_abs_flow = abs(external_flow) + abs(endogenous_flow)
        imbalance[t] = (external_flow + endogenous_flow) / (0.45 + total_abs_flow)
        volume[t] = 1.0 + 0.9 * total_abs_flow + 120.0 * abs(step_return)
        spread[t] = (
            4.0
            + 34.0 * (1.0 - current_depth)
            + 10.0 * total_abs_flow / current_depth
            + 1050.0 * abs(step_return)
        )

    step = np.arange(total + 1)
    return pd.DataFrame(
        {
            "step": step,
            "phase": np.where(step < config.n_pre, "pre", "post"),
            "price": np.exp(log_price),
            "log_return": log_return,
            "volume_index": volume,
            "spread_bps": spread,
            "depth": depth,
            "order_imbalance": imbalance,
            "stress": stress,
            "forced_flow": forced_flow,
            "shock_flow": shock_flow,
            "liquidation_inventory": liquidation_inventory,
            "hidden_leverage": hidden_leverage,
        }
    )


def path_metrics(frame: pd.DataFrame, config: ExperimentConfig) -> dict[str, float]:
    pre_anchor = float(frame.loc[config.n_pre - 1, "price"])
    post = frame.loc[config.n_pre:].copy()
    prices = post["price"].to_numpy(dtype=float)
    returns = post["log_return"].to_numpy(dtype=float)
    return {
        "terminal_return": float(prices[-1] / pre_anchor - 1.0),
        "max_drawdown": float(max(0.0, 1.0 - np.min(prices) / pre_anchor)),
        "realized_volatility": float(np.std(returns, ddof=1)),
        "peak_spread_bps": float(post["spread_bps"].max()),
        "minimum_depth": float(post["depth"].min()),
        "peak_volume_index": float(post["volume_index"].max()),
        "liquidation_fraction": float(
            1.0
            - post["liquidation_inventory"].iloc[-1]
            / max(frame["liquidation_inventory"].iloc[0], 1e-12)
        ),
    }


def bootstrap_ci(
    values: np.ndarray, seed: int, draws: int
) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(draws, dtype=float)
    for start in range(0, draws, 250):
        stop = min(draws, start + 250)
        idx = rng.integers(0, len(values), size=(stop - start, len(values)))
        means[start:stop] = values[idx].mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def run_dose_experiment(config: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    metric_rows: list[dict] = []
    path_rows: list[pd.DataFrame] = []
    exact_pre_max = 0.0
    zero_dose_post_max = 0.0

    for replicate in range(config.n_replicates):
        innovations = common_innovations(config, config.root_seed + 1009 * replicate)
        for dose in config.doses:
            frames = {
                world.name: simulate_market(world, innovations, config, dose)
                for world in (STABLE, FRAGILE)
            }
            pre_a = frames["stable"].loc[: config.n_pre - 1, OBSERVABLE_COLUMNS].to_numpy()
            pre_b = frames["fragile"].loc[: config.n_pre - 1, OBSERVABLE_COLUMNS].to_numpy()
            exact_pre_max = max(exact_pre_max, float(np.max(np.abs(pre_a - pre_b))))
            if dose == 0.0:
                post_a = frames["stable"].loc[config.n_pre :, OBSERVABLE_COLUMNS].to_numpy()
                post_b = frames["fragile"].loc[config.n_pre :, OBSERVABLE_COLUMNS].to_numpy()
                zero_dose_post_max = max(zero_dose_post_max, float(np.max(np.abs(post_a - post_b))))

            for world_name, frame in frames.items():
                metric_rows.append(
                    {
                        "replicate": replicate,
                        "dose": dose,
                        "world": world_name,
                        **path_metrics(frame, config),
                    }
                )
                if replicate == 0:
                    selected = frame.copy()
                    selected.insert(0, "world", world_name)
                    selected.insert(0, "dose", dose)
                    path_rows.append(selected)

    metrics = pd.DataFrame(metric_rows)
    representative = pd.concat(path_rows, ignore_index=True)
    summaries: list[dict] = []
    effect_metrics = (
        "max_drawdown",
        "terminal_return",
        "peak_spread_bps",
        "minimum_depth",
        "liquidation_fraction",
    )
    for dose in config.doses:
        subset = metrics[metrics["dose"] == dose]
        pivot = subset.pivot(index="replicate", columns="world", values=list(effect_metrics))
        for metric in effect_metrics:
            paired = pivot[(metric, "fragile")].to_numpy() - pivot[(metric, "stable")].to_numpy()
            low, high = bootstrap_ci(
                paired,
                config.root_seed + int(dose * 1000) + sum(ord(c) for c in metric),
                config.bootstrap_draws,
            )
            summaries.append(
                {
                    "dose": dose,
                    "metric": metric,
                    "stable_mean": float(pivot[(metric, "stable")].mean()),
                    "fragile_mean": float(pivot[(metric, "fragile")].mean()),
                    "paired_difference_mean": float(np.mean(paired)),
                    "paired_difference_ci_low": low,
                    "paired_difference_ci_high": high,
                    "positive_difference_fraction": float(np.mean(paired > 0.0)),
                }
            )
    summary = pd.DataFrame(summaries)
    diagnostics = {
        "pre_observable_max_abs_difference": exact_pre_max,
        "zero_dose_post_observable_max_abs_difference": zero_dose_post_max,
        "n_replicates": config.n_replicates,
        "doses": list(config.doses),
        "common_random_numbers": True,
        "world_specific_crash_branch": False,
    }
    return metrics, summary, representative, diagnostics


def sample_candidate_bank(config: ExperimentConfig) -> list[WorldParameters]:
    rng = np.random.default_rng(config.root_seed + CANDIDATE_BANK_SEED_OFFSET)
    bank: list[WorldParameters] = []
    for i in range(config.abc_bank_size):
        parameters = {
            name: float(rng.uniform(low, high))
            for name, (low, high) in CANDIDATE_PARAMETER_RANGES.items()
        }
        bank.append(
            WorldParameters(
                name=f"candidate_{i:04d}",
                **parameters,
            )
        )
    return bank


def probe_distance(
    candidate: pd.DataFrame,
    truth: pd.DataFrame,
    config: ExperimentConfig,
) -> float:
    start = config.n_pre
    stop = config.n_pre + config.abc_probe_horizon
    # Fixed engineering scales are declared in code before inspecting results.
    definitions = (
        ("log_return", 0.0030),
        ("spread_bps", 7.0),
        ("depth", 0.10),
        ("volume_index", 0.55),
    )
    pieces = []
    for column, scale in definitions:
        delta = (
            candidate.iloc[start:stop][column].to_numpy(dtype=float)
            - truth.iloc[start:stop][column].to_numpy(dtype=float)
        ) / scale
        pieces.append(delta)
    vector = np.concatenate(pieces)
    return float(np.sqrt(np.mean(vector**2)))


def normalized_parameter_distance(parameters: WorldParameters, truth: WorldParameters) -> float:
    squared = []
    for name, (low, high) in CANDIDATE_PARAMETER_RANGES.items():
        width = high - low
        squared.append(((getattr(parameters, name) - getattr(truth, name)) / width) ** 2)
    return float(np.sqrt(np.mean(squared)))


def run_abc_prototype(config: ExperimentConfig) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    innovations = common_innovations(config, config.root_seed + 88_888)
    truth_frame = simulate_market(ABC_TRUTH, innovations, config, config.abc_probe_dose)
    truth_metrics = path_metrics(truth_frame, config)
    bank = sample_candidate_bank(config)
    rows: list[dict] = []

    truth_pre = truth_frame.loc[: config.n_pre - 1, OBSERVABLE_COLUMNS].to_numpy(dtype=float)
    passive_max = 0.0
    for candidate in bank:
        frame = simulate_market(candidate, innovations, config, config.abc_probe_dose)
        pre = frame.loc[: config.n_pre - 1, OBSERVABLE_COLUMNS].to_numpy(dtype=float)
        pre_distance = float(np.max(np.abs(pre - truth_pre)))
        passive_max = max(passive_max, pre_distance)
        metrics = path_metrics(frame, config)
        rows.append(
            {
                **asdict(candidate),
                "passive_pre_max_abs_distance": pre_distance,
                "active_probe_distance": probe_distance(frame, truth_frame, config),
                "normalized_parameter_distance": normalized_parameter_distance(candidate, ABC_TRUTH),
                "terminal_return": metrics["terminal_return"],
                "max_drawdown": metrics["max_drawdown"],
                "peak_spread_bps": metrics["peak_spread_bps"],
                "minimum_depth": metrics["minimum_depth"],
            }
        )

    table = pd.DataFrame(rows).sort_values("active_probe_distance", kind="mergesort").reset_index(drop=True)
    accepted_n = max(1, int(round(config.abc_bank_size * config.abc_accept_fraction)))
    table["accepted_after_probe"] = False
    table.loc[: accepted_n - 1, "accepted_after_probe"] = True

    # Evaluate the selected candidates on an independent random stream and two
    # intervention doses that were not used for ranking.  The holdout response
    # RMSE is measured on exactly 30 points for four observables at both doses.
    holdout_innovations = common_innovations(
        config, config.root_seed + config.abc_holdout_seed_offset
    )
    holdout_truth_frames = {
        dose: simulate_market(ABC_TRUTH, holdout_innovations, config, dose)
        for dose in config.abc_holdout_doses
    }
    primary_holdout_dose = config.abc_holdout_doses[0]
    holdout_truth_metrics = path_metrics(
        holdout_truth_frames[primary_holdout_dose], config
    )
    holdout_definitions = (
        ("log_return", 0.0030),
        ("spread_bps", 7.0),
        ("depth", 0.10),
        ("volume_index", 0.55),
    )
    holdout_start = config.n_pre
    holdout_stop = holdout_start + config.abc_holdout_horizon
    holdout_rows: list[dict] = []
    for candidate in bank:
        candidate_frames = {
            dose: simulate_market(candidate, holdout_innovations, config, dose)
            for dose in config.abc_holdout_doses
        }
        pieces = []
        for dose in config.abc_holdout_doses:
            candidate_frame = candidate_frames[dose]
            truth_frame_holdout = holdout_truth_frames[dose]
            for column, scale in holdout_definitions:
                delta = (
                    candidate_frame.iloc[holdout_start:holdout_stop][column].to_numpy(dtype=float)
                    - truth_frame_holdout.iloc[holdout_start:holdout_stop][column].to_numpy(dtype=float)
                ) / scale
                pieces.append(delta)
        holdout_response_rmse = float(
            np.sqrt(np.mean(np.concatenate(pieces) ** 2))
        )
        metrics = path_metrics(candidate_frames[primary_holdout_dose], config)
        holdout_rows.append(
            {
                "name": candidate.name,
                "holdout_response_rmse": holdout_response_rmse,
                **{f"holdout_{key}": value for key, value in metrics.items()},
            }
        )
    table = table.merge(pd.DataFrame(holdout_rows), on="name", how="left", validate="one_to_one")
    posterior = table[table["accepted_after_probe"]]

    parameter_summary = []
    for name in CANDIDATE_PARAMETER_NAMES:
        parameter_summary.append(
            {
                "parameter": name,
                "truth": float(getattr(ABC_TRUTH, name)),
                "prior_median": float(table[name].median()),
                "posterior_median": float(posterior[name].median()),
                "posterior_q05": float(posterior[name].quantile(0.05)),
                "posterior_q95": float(posterior[name].quantile(0.95)),
            }
        )
    parameter_frame = pd.DataFrame(parameter_summary)

    in_sample_predictive = {}
    for metric in ("terminal_return", "max_drawdown", "peak_spread_bps", "minimum_depth"):
        prior_values = table[metric].to_numpy(dtype=float)
        post_values = posterior[metric].to_numpy(dtype=float)
        truth_value = float(truth_metrics[metric])
        in_sample_predictive[metric] = {
            "truth": truth_value,
            "prior_median": float(np.median(prior_values)),
            "posterior_median": float(np.median(post_values)),
            "prior_median_absolute_error": float(abs(np.median(prior_values) - truth_value)),
            "posterior_median_absolute_error": float(abs(np.median(post_values) - truth_value)),
            "prior_q05": float(np.quantile(prior_values, 0.05)),
            "prior_q95": float(np.quantile(prior_values, 0.95)),
            "posterior_q05": float(np.quantile(post_values, 0.05)),
            "posterior_q95": float(np.quantile(post_values, 0.95)),
        }

    holdout_predictive = {}
    for metric in ("terminal_return", "max_drawdown", "peak_spread_bps", "minimum_depth"):
        column = f"holdout_{metric}"
        prior_values = table[column].to_numpy(dtype=float)
        post_values = posterior[column].to_numpy(dtype=float)
        truth_value = float(holdout_truth_metrics[metric])
        holdout_predictive[metric] = {
            "truth": truth_value,
            "prior_median": float(np.median(prior_values)),
            "posterior_median": float(np.median(post_values)),
            "prior_median_absolute_error": float(abs(np.median(prior_values) - truth_value)),
            "posterior_median_absolute_error": float(abs(np.median(post_values) - truth_value)),
            "prior_q05": float(np.quantile(prior_values, 0.05)),
            "prior_q95": float(np.quantile(prior_values, 0.95)),
            "posterior_q05": float(np.quantile(post_values, 0.05)),
            "posterior_q95": float(np.quantile(post_values, 0.95)),
        }

    prior_holdout_rmse = table["holdout_response_rmse"].to_numpy(dtype=float)
    posterior_holdout_rmse = posterior["holdout_response_rmse"].to_numpy(dtype=float)
    holdout_response = {
        "prior_median_rmse": float(np.median(prior_holdout_rmse)),
        "posterior_median_rmse": float(np.median(posterior_holdout_rmse)),
        "relative_median_reduction": float(
            1.0 - np.median(posterior_holdout_rmse) / np.median(prior_holdout_rmse)
        ),
        "prior_q05": float(np.quantile(prior_holdout_rmse, 0.05)),
        "prior_q95": float(np.quantile(prior_holdout_rmse, 0.95)),
        "posterior_q05": float(np.quantile(posterior_holdout_rmse, 0.05)),
        "posterior_q95": float(np.quantile(posterior_holdout_rmse, 0.95)),
    }

    abc_summary = {
        "method": "rejection ABC over a finite prior bank",
        "bank_size": config.abc_bank_size,
        "passive_candidate_count": config.abc_bank_size,
        "accepted_after_probe": accepted_n,
        "accept_fraction": config.abc_accept_fraction,
        "accept_fraction_is_design_constant": True,
        "accepted_count_is_not_quality_metric": True,
        "probe_dose": config.abc_probe_dose,
        "probe_horizon": config.abc_probe_horizon,
        "passive_pre_max_abs_distance": passive_max,
        "candidate_generation": {
            "same_simulator_equations": True,
            "sampling_method": "independent uniform draws over eight declared parameter ranges",
            "parameter_names": list(CANDIDATE_PARAMETER_NAMES),
            "parameter_ranges": {
                name: [low, high]
                for name, (low, high) in CANDIDATE_PARAMETER_RANGES.items()
            },
            "bank_seed": config.root_seed + CANDIDATE_BANK_SEED_OFFSET,
            "bank_size": config.abc_bank_size,
            "not_separate_algorithms": True,
        },
        "prior_mean_normalized_parameter_distance": float(table["normalized_parameter_distance"].mean()),
        "posterior_mean_normalized_parameter_distance": float(
            posterior["normalized_parameter_distance"].mean()
        ),
        "selection_probe": {
            "dose": config.abc_probe_dose,
            "horizon": config.abc_probe_horizon,
            "innovation_seed": config.root_seed + 88_888,
        },
        "independent_holdout": {
            "doses": list(config.abc_holdout_doses),
            "horizon_points_per_dose": config.abc_holdout_horizon,
            "innovation_seed": config.root_seed + config.abc_holdout_seed_offset,
            "used_for_candidate_ranking": False,
        },
        "in_sample_predictive": in_sample_predictive,
        "predictive": holdout_predictive,
        "holdout_response": holdout_response,
        "limitations": [
            "The true world is synthetic and belongs to the same parametric family as the bank.",
            "Candidate selection uses common innovations to isolate structural identification; the reported response check uses an independent innovation stream and two held-out doses.",
            "Rejection ABC is a proof of concept, not a production posterior or a causal estimate on real data.",
        ],
    }
    return table, abc_summary, parameter_frame


def draw_axes(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    x_values: Iterable[float],
    y_values: Iterable[float],
    x_label: str,
    y_label: str,
) -> tuple[callable, callable]:
    left, top, right, bottom = box
    xs = np.asarray(list(x_values), dtype=float)
    ys = np.asarray(list(y_values), dtype=float)
    x_min, x_max = float(xs.min()), float(xs.max())
    y_min, y_max = float(ys.min()), float(ys.max())
    if math.isclose(x_min, x_max):
        x_max = x_min + 1.0
    if math.isclose(y_min, y_max):
        y_max = y_min + 1.0
    y_pad = 0.10 * (y_max - y_min)
    y_min -= y_pad
    y_max += y_pad

    def xp(value: float) -> int:
        return int(left + (value - x_min) / (x_max - x_min) * (right - left))

    def yp(value: float) -> int:
        return int(bottom - (value - y_min) / (y_max - y_min) * (bottom - top))

    for i in range(5):
        y = top + i * (bottom - top) / 4
        draw.line((left, y, right, y), fill=GRID, width=2)
        value = y_max - i * (y_max - y_min) / 4
        draw.text((left - 12, y), f"{value:.3g}", anchor="rm", fill=GRAY, font=font(22))
    draw.line((left, top, left, bottom), fill=NAVY, width=3)
    draw.line((left, bottom, right, bottom), fill=NAVY, width=3)
    draw.text(((left + right) // 2, bottom + 52), x_label, anchor="mm", fill=NAVY, font=font(25))
    if y_label:
        draw.text((left, top - 38), y_label, anchor="ls", fill=NAVY, font=font(25, True))
    return xp, yp


def make_exact_twin_figure(representative: pd.DataFrame, config: ExperimentConfig, path: Path) -> None:
    width, height = 1600, 1000
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "S0 同迹异构：冲击前完全同迹，冲击后因隐含结构分叉", fill=NAVY, font=font(42, True))
    draw.text((80, 112), "代表路径，dose = 2.0；两个世界使用同一未来随机创新", fill=GRAY, font=font(27))

    subset = representative[representative["dose"] == 2.0]
    steps = subset["step"].unique()
    price_values = subset["price"].to_numpy(dtype=float)
    xp, yp = draw_axes(draw, (145, 210, 1510, 610), steps, price_values, "step", "price")
    colors = {"stable": BLUE, "fragile": RED}
    for world in ("stable", "fragile"):
        frame = subset[subset["world"] == world]
        points = [(xp(float(x)), yp(float(y))) for x, y in zip(frame["step"], frame["price"])]
        draw.line(points, fill=colors[world], width=5)
    shock_x = xp(float(config.n_pre))
    draw.line((shock_x, 210, shock_x, 610), fill=GOLD, width=4)
    draw.text((shock_x + 10, 222), "外生卖出介入", fill=GOLD, font=font(24, True))
    draw.line((1080, 155, 1135, 155), fill=BLUE, width=6)
    draw.text((1148, 155), "stable", anchor="lm", fill=NAVY, font=font(25))
    draw.line((1260, 155, 1315, 155), fill=RED, width=6)
    draw.text((1328, 155), "fragile", anchor="lm", fill=NAVY, font=font(25))

    depth_values = subset["depth"].to_numpy(dtype=float)
    xp2, yp2 = draw_axes(draw, (145, 705, 1510, 900), steps, depth_values, "step", "depth")
    for world in ("stable", "fragile"):
        frame = subset[subset["world"] == world]
        points = [(xp2(float(x)), yp2(float(y))) for x, y in zip(frame["step"], frame["depth"])]
        draw.line(points, fill=colors[world], width=5)
    shock_x2 = xp2(float(config.n_pre))
    draw.line((shock_x2, 705, shock_x2, 900), fill=GOLD, width=4)
    image.save(path, quality=95)


def make_dose_figure(summary: pd.DataFrame, path: Path) -> None:
    width, height = 1600, 920
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "冲击剂量曲线：隐含结构决定反事实响应", fill=NAVY, font=font(42, True))
    draw.text((80, 112), "线为配对差值均值（fragile − stable）；误差棒为 95% bootstrap CI", fill=GRAY, font=font(27))

    panels = [
        ("max_drawdown", "最大回撤差", BLUE),
        ("terminal_return", "终值收益差", RED),
        ("peak_spread_bps", "峰值价差差 (bps)", GOLD),
    ]
    panel_boxes = [(120, 220, 510, 760), (605, 220, 995, 760), (1090, 220, 1480, 760)]
    for (metric, label, color), box in zip(panels, panel_boxes):
        frame = summary[summary["metric"] == metric].sort_values("dose")
        x = frame["dose"].to_numpy(dtype=float)
        mean = frame["paired_difference_mean"].to_numpy(dtype=float)
        low = frame["paired_difference_ci_low"].to_numpy(dtype=float)
        high = frame["paired_difference_ci_high"].to_numpy(dtype=float)
        xp, yp = draw_axes(draw, box, x, np.concatenate([low, high, [0.0]]), "dose", label)
        draw.line((box[0], yp(0.0), box[2], yp(0.0)), fill=GRAY, width=2)
        points = [(xp(float(a)), yp(float(b))) for a, b in zip(x, mean)]
        draw.line(points, fill=color, width=6)
        for a, m, lo, hi in zip(x, mean, low, high):
            px = xp(float(a))
            draw.line((px, yp(float(lo)), px, yp(float(hi))), fill=color, width=4)
            draw.ellipse((px - 7, yp(float(m)) - 7, px + 7, yp(float(m)) + 7), fill=color)
            draw.text((px, box[3] + 18), f"{a:g}", anchor="ma", fill=GRAY, font=font(21))
    image.save(path, quality=95)


def make_abc_figure(bank: pd.DataFrame, parameters: pd.DataFrame, path: Path) -> None:
    width, height = 1600, 1040
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), "候选世界重建：主动探针不是筛掉多少，而是误差是否下降", fill=NAVY, font=font(40, True))
    draw.text((80, 112), "有限先验库 + rejection ABC；700→70 是固定接受 10% 的设计，不是实验成绩", fill=GRAY, font=font(25))

    accepted = bank[bank["accepted_after_probe"]]
    rejected = bank[~bank["accepted_after_probe"]]
    x_all = bank["margin_buffer"].to_numpy(dtype=float)
    y_all = bank["leverage"].to_numpy(dtype=float)
    xp, yp = draw_axes(draw, (130, 220, 980, 800), x_all, y_all, "margin buffer", "leverage")
    for _, row in rejected.iterrows():
        x, y = xp(float(row["margin_buffer"])), yp(float(row["leverage"]))
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill="#BBC5CC")
    for _, row in accepted.iterrows():
        x, y = xp(float(row["margin_buffer"])), yp(float(row["leverage"]))
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=BLUE)
    truth_x, truth_y = xp(ABC_TRUTH.margin_buffer), yp(ABC_TRUTH.leverage)
    draw.line((truth_x - 12, truth_y, truth_x + 12, truth_y), fill=RED, width=5)
    draw.line((truth_x, truth_y - 12, truth_x, truth_y + 12), fill=RED, width=5)
    draw.text((truth_x + 16, truth_y - 15), "synthetic truth", fill=RED, font=font(22, True))

    draw.rounded_rectangle((1060, 220, 1500, 800), radius=18, fill=LIGHT, outline=GRID, width=3)
    draw.text((1100, 260), "参数中位数：先验 → 后验", fill=NAVY, font=font(29, True))
    y = 330
    selected = parameters[parameters["parameter"].isin(["leverage", "margin_buffer", "crowding", "liquidity_withdrawal"])]
    labels = {
        "leverage": "leverage",
        "margin_buffer": "margin buffer",
        "crowding": "crowding",
        "liquidity_withdrawal": "liquidity withdrawal",
    }
    for _, row in selected.iterrows():
        draw.text((1100, y), labels[str(row["parameter"])], fill=GRAY, font=font(23))
        draw.text(
            (1100, y + 34),
            f"{row['prior_median']:.3f}  →  {row['posterior_median']:.3f}",
            fill=BLUE,
            font=font(27, True),
        )
        # Give the truth label its own row: CJK fallback fonts have different widths.
        draw.text((1100, y + 68), f"truth {row['truth']:.3f}", fill=RED, font=font(20))
        y += 100
    draw.text((1100, 748), f"灰色：全部候选 {len(bank)}", fill=GRAY, font=font(21))
    draw.text((1100, 775), f"蓝色：固定接受 {len(accepted)}（10%）", fill=BLUE, font=font(21, True))

    prior_parameter = float(bank["normalized_parameter_distance"].mean())
    posterior_parameter = float(accepted["normalized_parameter_distance"].mean())
    prior_holdout = float(bank["holdout_response_rmse"].median())
    posterior_holdout = float(accepted["holdout_response_rmse"].median())
    draw.rounded_rectangle((80, 890, 1520, 1005), radius=18, fill=LIGHT, outline=GRID, width=3)
    draw.text((115, 915), "真正的质量检查（越低越好）", fill=NAVY, font=font(25, True))
    draw.text(
        (535, 915),
        f"参数距离  {prior_parameter:.3f} → {posterior_parameter:.3f}",
        fill=BLUE,
        font=font(25, True),
    )
    draw.text(
        (1035, 915),
        f"独立 holdout RMSE  {prior_holdout:.3f} → {posterior_holdout:.3f}",
        fill=RED,
        font=font(25, True),
    )
    draw.text((115, 963), "holdout 使用独立随机创新、未参与筛选的 dose=2 和 4。", fill=GRAY, font=font(21))
    image.save(path, quality=95)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_ready(value):
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def validate_existing(output_dir: Path) -> dict:
    data_dir = output_dir / "data"
    figure_dir = output_dir / "figures"
    required = [
        data_dir / "experiment_config.json",
        data_dir / "dose_path_metrics.csv",
        data_dir / "dose_effect_summary.csv",
        data_dir / "representative_paths.csv",
        data_dir / "abc_candidate_bank.csv",
        data_dir / "abc_parameter_summary.csv",
        data_dir / "experiment_metrics.json",
        figure_dir / "s0_exact_twins.png",
        figure_dir / "dose_response.png",
        figure_dir / "abc_candidate_worlds.png",
        output_dir / "README.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    checks: dict[str, dict] = {}
    checks["required_files"] = {"passed": not missing, "missing": missing}
    if missing:
        report = {"passed": False, "checks": checks}
        return report

    config = json.loads((data_dir / "experiment_config.json").read_text(encoding="utf-8"))
    metrics = pd.read_csv(data_dir / "dose_path_metrics.csv")
    summary = pd.read_csv(data_dir / "dose_effect_summary.csv")
    paths = pd.read_csv(data_dir / "representative_paths.csv")
    bank = pd.read_csv(data_dir / "abc_candidate_bank.csv")
    headline = json.loads((data_dir / "experiment_metrics.json").read_text(encoding="utf-8"))

    numeric_metrics = metrics.select_dtypes(include=[np.number]).to_numpy()
    checks["finite_metrics"] = {"passed": bool(np.isfinite(numeric_metrics).all())}
    checks["row_count"] = {
        "passed": len(metrics) == int(config["n_replicates"]) * len(config["doses"]) * 2,
        "actual": len(metrics),
    }
    checks["dose_grid"] = {
        "passed": sorted(metrics["dose"].unique().tolist()) == sorted(config["doses"]),
        "actual": sorted(metrics["dose"].unique().tolist()),
    }
    checks["exact_pre_twins"] = {
        "passed": headline["dose_experiment"]["pre_observable_max_abs_difference"] <= 1e-12,
        "maximum_absolute_difference": headline["dose_experiment"]["pre_observable_max_abs_difference"],
    }
    checks["zero_dose_control"] = {
        "passed": headline["dose_experiment"]["zero_dose_post_observable_max_abs_difference"] <= 1e-12,
        "maximum_absolute_difference": headline["dose_experiment"]["zero_dose_post_observable_max_abs_difference"],
    }
    duplicated_pre = paths[paths["step"] < int(config["n_pre"])].pivot_table(
        index=["dose", "step"], columns="world", values=list(OBSERVABLE_COLUMNS)
    )
    max_diff = 0.0
    for column in OBSERVABLE_COLUMNS:
        delta = np.abs(duplicated_pre[(column, "stable")] - duplicated_pre[(column, "fragile")])
        max_diff = max(max_diff, float(delta.max()))
    checks["representative_pre_recomputed"] = {
        "passed": max_diff <= 1e-12,
        "maximum_absolute_difference": max_diff,
    }
    expected_accepted = max(1, int(round(int(config["abc_bank_size"]) * float(config["abc_accept_fraction"]))))
    abc_metadata = headline["abc"]
    candidate_metadata = abc_metadata["candidate_generation"]
    checks["abc_bank_shape"] = {
        "passed": len(bank) == int(config["abc_bank_size"])
        and all(name in bank.columns for name in CANDIDATE_PARAMETER_NAMES),
        "actual_rows": len(bank),
        "expected_rows": int(config["abc_bank_size"]),
        "parameter_columns": len([name for name in CANDIDATE_PARAMETER_NAMES if name in bank.columns]),
    }
    checks["abc_unique_candidate_worlds"] = {
        "passed": bank["name"].nunique() == len(bank)
        and len(bank[list(CANDIDATE_PARAMETER_NAMES)].drop_duplicates()) == len(bank),
        "unique_names": int(bank["name"].nunique()),
        "unique_parameter_rows": int(len(bank[list(CANDIDATE_PARAMETER_NAMES)].drop_duplicates())),
    }
    ranges_valid = True
    invalid_ranges: list[str] = []
    for name, (low, high) in CANDIDATE_PARAMETER_RANGES.items():
        if name not in bank.columns or not bank[name].between(low, high, inclusive="both").all():
            ranges_valid = False
            invalid_ranges.append(name)
    checks["abc_declared_parameter_ranges"] = {
        "passed": ranges_valid,
        "invalid_parameters": invalid_ranges,
    }
    checks["abc_generation_metadata"] = {
        "passed": bool(candidate_metadata["same_simulator_equations"])
        and bool(candidate_metadata["not_separate_algorithms"])
        and candidate_metadata["parameter_names"] == list(CANDIDATE_PARAMETER_NAMES)
        and int(candidate_metadata["bank_size"]) == int(config["abc_bank_size"])
        and int(candidate_metadata["bank_seed"])
        == int(config["root_seed"]) + CANDIDATE_BANK_SEED_OFFSET,
    }
    replay_rng = np.random.default_rng(int(candidate_metadata["bank_seed"]))
    replay_matrix = np.array(
        [
            [replay_rng.uniform(low, high) for low, high in CANDIDATE_PARAMETER_RANGES.values()]
            for _ in range(len(bank))
        ],
        dtype=float,
    )
    observed_matrix = (
        bank.sort_values("name", kind="mergesort")[list(CANDIDATE_PARAMETER_NAMES)]
        .to_numpy(dtype=float)
    )
    checks["abc_bank_replays_from_declared_seed"] = {
        "passed": bool(np.allclose(observed_matrix, replay_matrix, rtol=0.0, atol=5e-12)),
        "seed": int(candidate_metadata["bank_seed"]),
    }
    checks["abc_acceptance_count"] = {
        "passed": int(bank["accepted_after_probe"].sum()) == expected_accepted
        and bool(abc_metadata["accept_fraction_is_design_constant"])
        and bool(abc_metadata["accepted_count_is_not_quality_metric"]),
        "actual": int(bank["accepted_after_probe"].sum()),
        "expected": expected_accepted,
    }
    expected_accepted_names = set(
        bank.sort_values("active_probe_distance", kind="mergesort")
        .head(expected_accepted)["name"]
        .tolist()
    )
    actual_accepted_names = set(bank.loc[bank["accepted_after_probe"], "name"].tolist())
    checks["abc_acceptance_matches_probe_ranking"] = {
        "passed": actual_accepted_names == expected_accepted_names,
        "mismatched_name_count": len(actual_accepted_names.symmetric_difference(expected_accepted_names)),
    }
    checks["abc_independent_holdout"] = {
        "passed": not bool(abc_metadata["independent_holdout"]["used_for_candidate_ranking"])
        and list(abc_metadata["independent_holdout"]["doses"])
        == list(config["abc_holdout_doses"]),
    }
    boundary = headline["implementation_boundary"]
    checks["terminal_target_marked_not_implemented"] = {
        "passed": boundary["current_stage"] == "synthetic_same_family_proof_of_concept"
        and boundary["terminal_target"]["status"] == "aspirational_not_implemented"
        and "physical robot validation" in boundary["not_implemented"],
    }
    checks["abc_passive_nonidentifiability"] = {
        "passed": float(bank["passive_pre_max_abs_distance"].max()) <= 1e-12,
        "maximum_absolute_distance": float(bank["passive_pre_max_abs_distance"].max()),
    }
    checks["summary_complete"] = {
        "passed": len(summary) == len(config["doses"]) * 5,
        "actual": len(summary),
    }
    checks["figures_readable"] = {
        "passed": all(Image.open(path).size[0] >= 1200 and Image.open(path).size[1] >= 800 for path in required if path.suffix == ".png")
    }
    passed = all(item["passed"] for item in checks.values())
    return {"passed": passed, "checks": checks}


def write_readme(output_dir: Path, config: ExperimentConfig, metrics: dict) -> None:
    dose = metrics["headline_dose_2"]
    abc = metrics["abc"]
    content = f"""# MarketGenesis v2 同迹异构合成实验

## 实验定位

这是命题 `h(S1) = h(S2)` 但 `F(S1) != F(S2)` 的一个可复现**合成存在性证明**。两个市场使用完全相同的动力学方程和共同随机创新，但隐含杠杆、库存、保证金缓冲、拥挤度和流动性规则不同。在约束未激活时，六类声明观测量逐步完全相同；此后用同一个外生卖出母单，按事先固定的剂量网格探测两种结构。

这不是真实市场的经验发现，不是 alpha 策略或交易系统，也不证明真实市场的潜在状态已经被恢复。

## 复现命令

```bash
python3 reproduce.py
```

根随机种子为 `{config.root_seed}`，重复 `{config.n_replicates}` 次，剂量为 `{list(config.doses)}`。每一次 stable/fragile 对比均使用共同随机数（common random numbers）。

## 核心检查与实测结果

- 介入前，价格、收益率、成交量、价差、深度和订单不平衡的最大绝对差：`{metrics['dose_experiment']['pre_observable_max_abs_difference']:.3e}`。
- 零剂量对照中，stable/fragile 在介入时点后的最大观测差：`{metrics['dose_experiment']['zero_dose_post_observable_max_abs_difference']:.3e}`。
- 剂量 2.0 时，最大回撤的配对差（fragile − stable）为 `{dose['max_drawdown']['mean']:.6f}`，95% bootstrap CI 为 `[{dose['max_drawdown']['ci_low']:.6f}, {dose['max_drawdown']['ci_high']:.6f}]`。
- 剂量 2.0 时，终值收益率的配对差为 `{dose['terminal_return']['mean']:.6f}`，95% bootstrap CI 为 `[{dose['terminal_return']['ci_low']:.6f}, {dose['terminal_return']['ci_high']:.6f}]`。
- ABC 固定接受 `{abc['accept_fraction']*100:.0f}%`，所以 `{abc['bank_size']}→{abc['accepted_after_probe']}` 是设计常数，不是质量结果。
- 候选参数与合成真值的平均标准化距离，由 `{abc['prior_mean_normalized_parameter_distance']:.4f}` 降至 `{abc['posterior_mean_normalized_parameter_distance']:.4f}`。
- 独立 holdout 响应 RMSE 由 `{abc['holdout_response']['prior_median_rmse']:.4f}` 降至 `{abc['holdout_response']['posterior_median_rmse']:.4f}`。

## 700 个候选世界是怎么来的

程序不是人工编出 700 个故事，也不是运行 700 种不同算法。它在同一套市场动力学方程中，从 8 个事先声明的参数范围独立均匀抽样：杠杆、隐藏库存、保证金缓冲、强制平仓基准与敏感度、拥挤度、流动性撤回、库存对流动性的影响。随机种子、参数名与取值范围全部写入 `experiment_metrics.json`并由验证器复播。

`{abc['bank_size']}→{abc['accepted_after_probe']}` 来自固定的 `{abc['accept_fraction'] * 100:.0f}%` 保留比例，所以它是**设计常数，不是识别成绩**。质量要看参数距离，以及未参与排名的独立随机创新和 dose=2/4 下的 holdout 响应 RMSE。

## 交付文件

- `data/dose_path_metrics.csv`：每个重复、剂量与世界一行的路径指标。
- `data/dose_effect_summary.csv`：配对差值与 bootstrap 置信区间。
- `data/representative_paths.csv`：每个剂量、两个世界的完整代表路径。
- `data/abc_candidate_bank.csv`：有限先验库、探测距离与接受标记。
- `data/abc_parameter_summary.csv`：真值/先验/后验参数摘要。
- `data/experiment_metrics.json`：机器可读的核心结果、支持和不支持的主张。
- `data/artifact_hashes.sha256`：所有生成数据和图表的哈希。
- `figures/*.png`：三张由程序直接生成的结果图。
- `validation_report.json`：独立输出检查。

## 模型机制

所有世界使用同一个价格形成函数。每一步都统一计算回撤、保证金缺口、通用强制平仓、内生订单流、深度撤回和价格冲击。代码不根据 `stable` 或 `fragile` 标签分支；标签只选择参数。两个世界的外生母单完全相同，零剂量是负对照。

rejection-ABC 雏形故意从一组都能精确复现被动介入前轨迹的候选世界出发。它施加有限探测，比较可观测响应向量，保留距离最近的 {int(config.abc_accept_fraction * 100)}%。这演示了候选世界工作流，不意味着一般性识别难题已经解决。

## 终极目标与实现边界

当前交付物只实现了透明人工市场、有限候选库、主动探针和独立 holdout。终极目标是主动式多假设世界模型：持续生成与证据相容的候选世界，预演不同干预下的未来分叉，选择信息量最大且低风险的探针，并在真实机制尚未确定时寻找跨多个世界都稳健的行动。真实市场校准、学习式生成器、稳健规划和实体机器人验证尚未完成。

## 局限

1. 该市场是约化的合成动力系统，不是经交易所数据校准的限价订单簿模型。
2. 介入前的精确相等是构造性的：隐含机制在安静区间休眠。它以反例证明不可识别性可以存在，不证明它在真实市场中的普遍程度。
3. 结构族、剂量网格、时域和 ABC 缩放均是研究者选择，后续必须补充敏感性分析。
4. ABC 真值与候选库属于同一参数族，而且共同创新使反演问题显著易于真实数据。
5. 置信区间只量化模拟器内部的 Monte Carlo 变异，不支持对金融市场总体的统计推断。
6. 实验不涉及真实资金、自动下单、券商 API 或任何盈利主张。
"""
    (output_dir / "README.md").write_text(content, encoding="utf-8")


def run(output_dir: Path, quick: bool = False) -> dict:
    config = ExperimentConfig()
    if quick:
        config = ExperimentConfig(
            n_replicates=24,
            bootstrap_draws=300,
            abc_bank_size=120,
        )
    data_dir = output_dir / "data"
    figure_dir = output_dir / "figures"
    data_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    dose_metrics, dose_summary, representative, diagnostics = run_dose_experiment(config)
    abc_bank, abc_summary, abc_parameters = run_abc_prototype(config)

    dose_metrics.to_csv(data_dir / "dose_path_metrics.csv", index=False, float_format="%.12g")
    dose_summary.to_csv(data_dir / "dose_effect_summary.csv", index=False, float_format="%.12g")
    representative.to_csv(data_dir / "representative_paths.csv", index=False, float_format="%.12g")
    abc_bank.to_csv(data_dir / "abc_candidate_bank.csv", index=False, float_format="%.12g")
    abc_parameters.to_csv(data_dir / "abc_parameter_summary.csv", index=False, float_format="%.12g")

    config_dict = asdict(config)
    config_dict["doses"] = list(config.doses)
    config_dict["stable_parameters"] = asdict(STABLE)
    config_dict["fragile_parameters"] = asdict(FRAGILE)
    config_dict["abc_truth_parameters"] = asdict(ABC_TRUTH)
    (data_dir / "experiment_config.json").write_text(
        json.dumps(json_ready(config_dict), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    headline_dose_2 = {}
    for metric in ("max_drawdown", "terminal_return", "peak_spread_bps", "minimum_depth"):
        row = dose_summary[(dose_summary["dose"] == 2.0) & (dose_summary["metric"] == metric)].iloc[0]
        headline_dose_2[metric] = {
            "mean": float(row["paired_difference_mean"]),
            "ci_low": float(row["paired_difference_ci_low"]),
            "ci_high": float(row["paired_difference_ci_high"]),
            "positive_difference_fraction": float(row["positive_difference_fraction"]),
        }

    metrics = {
        "schema_version": "marketgenesis-result-v2.2",
        "status": "synthetic_result_not_real_market_evidence",
        "dose_experiment": diagnostics,
        "headline_dose_2": headline_dose_2,
        "abc": abc_summary,
        "claims_supported": [
            "Within this declared simulator, distinct hidden structures can generate identical passive observables.",
            "Within this declared simulator, the same intervention and same innovations can reveal different responses.",
            "A finite active probe can reduce a synthetic candidate-world set under a same-family ABC prototype.",
        ],
        "claims_not_supported": [
            "That real market prices are generated by these specific hidden states.",
            "That the model predicts tradable alpha or is profitable.",
            "That the latent state of a real market is uniquely identifiable.",
        ],
        "limitations": abc_summary["limitations"],
        "implementation_boundary": {
            "current_stage": "synthetic_same_family_proof_of_concept",
            "implemented": [
                "transparent synthetic market generator",
                "finite candidate-world bank",
                "active-probe rejection ABC",
                "independent synthetic holdout",
            ],
            "not_implemented": [
                "real-market calibration",
                "learned candidate-world generator",
                "production Bayesian posterior",
                "counterfactual robust planner",
                "physical robot validation",
            ],
            "terminal_target": {
                "name": "Active Multi-Hypothesis World Model",
                "status": "aspirational_not_implemented",
                "outputs": [
                    "candidate world distribution",
                    "conditional future branching tree",
                    "next informative low-risk probe",
                    "robust action across plausible worlds",
                ],
            },
        },
    }
    (data_dir / "experiment_metrics.json").write_text(
        json.dumps(json_ready(metrics), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    make_exact_twin_figure(representative, config, figure_dir / "s0_exact_twins.png")
    make_dose_figure(dose_summary, figure_dir / "dose_response.png")
    make_abc_figure(abc_bank, abc_parameters, figure_dir / "abc_candidate_worlds.png")
    write_readme(output_dir, config, metrics)

    hash_targets = sorted(
        [
            path
            for path in data_dir.iterdir()
            if path.is_file() and path.name != "artifact_hashes.sha256"
        ]
        + [path for path in figure_dir.iterdir() if path.is_file()]
    )
    with (data_dir / "artifact_hashes.sha256").open("w", encoding="utf-8") as handle:
        for path in hash_targets:
            handle.write(f"{sha256(path)}  {path.relative_to(output_dir)}\n")

    validation = validate_existing(output_dir)
    (output_dir / "validation_report.json").write_text(
        json.dumps(json_ready(validation), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not validation["passed"]:
        raise RuntimeError("Generated artifacts failed validation; inspect validation_report.json")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="MarketGenesis v2 synthetic doppelganger experiment")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--quick", action="store_true", help="Run a small pipeline smoke test")
    parser.add_argument("--validate-existing", action="store_true")
    args = parser.parse_args()
    if args.validate_existing:
        report = validate_existing(args.output)
        print(json.dumps(json_ready(report), ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["passed"] else 1)
    metrics = run(args.output, quick=args.quick)
    print(json.dumps(json_ready(metrics), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

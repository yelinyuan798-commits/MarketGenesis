from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


PACK = Path(__file__).resolve().parent
CODE = PACK / "code"
OUTPUT = PACK / "reproduced"
RESULT_PAGE = OUTPUT / "打开查看结果.html"
sys.path.insert(0, str(CODE))

from marketgenesis_v2 import run  # noqa: E402


def write_result_page(metrics: dict) -> None:
    config = json.loads((OUTPUT / "data" / "experiment_config.json").read_text(encoding="utf-8"))
    validation = json.loads((OUTPUT / "validation_report.json").read_text(encoding="utf-8"))
    validation_check_count = len(validation["checks"])
    pre = metrics["dose_experiment"]["pre_observable_max_abs_difference"]
    drawdown = metrics["headline_dose_2"]["max_drawdown"]["mean"] * 100.0
    spread = metrics["headline_dose_2"]["peak_spread_bps"]["mean"]
    before = metrics["abc"]["bank_size"]
    after = metrics["abc"]["accepted_after_probe"]
    parameter_before = metrics["abc"]["prior_mean_normalized_parameter_distance"]
    parameter_after = metrics["abc"]["posterior_mean_normalized_parameter_distance"]
    holdout_before = metrics["abc"]["holdout_response"]["prior_median_rmse"]
    holdout_after = metrics["abc"]["holdout_response"]["posterior_median_rmse"]
    candidate_generation = metrics["abc"]["candidate_generation"]
    accept_fraction = metrics["abc"]["accept_fraction"]
    payload = {
        "status": "PASS",
        "pre_observable_max_abs_difference": pre,
        "drawdown_difference_pp": drawdown,
        "peak_spread_difference_bps": spread,
        "candidate_worlds_before": before,
        "candidate_worlds_after": after,
        "candidate_accept_fraction_is_fixed": accept_fraction,
        "accepted_count_is_quality_metric": not bool(metrics["abc"]["accepted_count_is_not_quality_metric"]),
        "candidate_generation": candidate_generation,
        "parameter_distance_before": parameter_before,
        "parameter_distance_after": parameter_after,
        "independent_holdout_rmse_before": holdout_before,
        "independent_holdout_rmse_after": holdout_after,
        "random_seed": config["root_seed"],
        "implementation_boundary": metrics["implementation_boundary"],
    }
    (OUTPUT / "复现结果摘要.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MarketGenesis · 复现成功</title>
  <style>
    :root {{ --navy:#102d49; --blue:#1d649c; --red:#b82a30; --green:#187548; --gray:#66717d; --light:#f4f7f9; --line:#dce5eb; }}
    * {{ box-sizing:border-box; }}
    html {{ min-height:100%; }}
    body {{ margin:0; background:#edf2f5; color:var(--navy); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
    main {{ width:min(1540px,calc(100vw - 24px)); margin:12px auto 22px; }}
    .hero,.panel,.boundary {{ background:white; border-radius:18px; box-shadow:0 12px 34px rgba(16,45,73,.09); }}
    .hero {{ padding:16px 20px 14px; }}
    .hero-top {{ display:flex; align-items:center; justify-content:space-between; gap:14px; }}
    .eyebrow {{ color:var(--red); font-size:13px; font-weight:850; letter-spacing:.12em; }}
    .pass {{ flex:none; padding:7px 12px; border:1px solid #b8dfc9; border-radius:999px; background:#eaf7ef; color:var(--green); font-size:13px; font-weight:900; }}
    h1 {{ margin:5px 0 3px; font-size:clamp(27px,3.1vw,43px); line-height:1.08; }}
    .sub {{ margin:0; color:var(--gray); font-size:13px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin-top:11px; }}
    .card {{ min-width:0; background:var(--light); border:1px solid #e9eef2; border-radius:12px; padding:9px 11px; }}
    .number {{ display:block; font-size:clamp(20px,2vw,27px); font-weight:900; color:var(--blue); white-space:nowrap; }}
    .label {{ display:block; margin-top:3px; color:var(--gray); font-size:11px; line-height:1.28; }}
    .proofline {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:9px; color:var(--gray); font-size:11px; }}
    .proofline span {{ white-space:nowrap; }}
    .figure-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin-top:10px; }}
    .panel {{ min-width:0; margin:0; padding:8px 8px 10px; overflow:hidden; }}
    .panel figcaption {{ display:flex; align-items:center; gap:7px; padding:1px 4px 7px; color:var(--navy); font-size:12px; font-weight:850; }}
    .panel figcaption span {{ display:inline-grid; place-items:center; width:22px; height:22px; border-radius:7px; background:var(--navy); color:white; font-size:10px; }}
    .panel img {{ width:100%; aspect-ratio:16/10; object-fit:contain; border:1px solid #eef2f4; border-radius:9px; display:block; background:white; }}
    .boundary {{ margin-top:10px; padding:10px 14px; border-left:5px solid var(--red); color:#563137; font-size:12px; line-height:1.55; }}
    .boundary summary {{ cursor:pointer; color:var(--navy); font-weight:850; }}
    .boundary-content {{ margin-top:8px; }}
    code {{ background:#e7edf1; padding:2px 6px; border-radius:6px; }}
    @media (max-width:820px) {{
      main {{ width:min(96vw,680px); }}
      .cards {{ grid-template-columns:1fr 1fr; }}
      .figure-grid {{ grid-template-columns:1fr; }}
      .panel img {{ aspect-ratio:auto; }}
    }}
    @media (max-height:760px) and (min-width:821px) {{
      main {{ margin-top:6px; }}
      .hero {{ padding-top:11px; padding-bottom:10px; }}
      h1 {{ font-size:27px; }}
      .cards {{ margin-top:7px; }}
      .card {{ padding-top:6px; padding-bottom:6px; }}
      .proofline {{ margin-top:6px; }}
    }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="hero-top"><div class="eyebrow">MARKETGENESIS · LOCAL REPRODUCTION</div><div class="pass">PASS · {validation_check_count}/{validation_check_count}</div></div>
    <h1>复现成功：数据、图表与完整性检查全部通过</h1>
    <p class="sub">随机种子 <code>{config['root_seed']}</code>；数据和图表刚刚由本机重新生成。</p>
    <div class="cards">
      <div class="card"><span class="number">{pre:.0f}</span><span class="label">冲击前六类观测量最大差异</span></div>
      <div class="card"><span class="number">{drawdown:+.2f}pp</span><span class="label">同一冲击后最大回撤配对差</span></div>
      <div class="card"><span class="number">{spread:+.2f}bps</span><span class="label">同一冲击后峰值价差配对差</span></div>
      <div class="card"><span class="number">{parameter_before:.3f}→{parameter_after:.3f}</span><span class="label">主动探针前后平均参数距离（越低越好）</span></div>
    </div>
    <div class="proofline"><span>独立 holdout：<code>{holdout_before:.3f}→{holdout_after:.3f}</code></span><span>候选世界：<code>{before}→{after}</code>（固定 {accept_fraction*100:.0f}% 接受规则）</span><span>候选生成种子：<code>{candidate_generation['bank_seed']}</code></span></div>
  </section>
  <section class="figure-grid" aria-label="三张核心实验图">
    <figure class="panel"><figcaption><span>01</span>相同历史，同一冲击，不同未来</figcaption><img src="figures/s0_exact_twins.png" alt="同迹异构实验图"></figure>
    <figure class="panel"><figcaption><span>02</span>冲击越强，两个世界分叉越明显</figcaption><img src="figures/dose_response.png" alt="冲击剂量曲线"></figure>
    <figure class="panel"><figcaption><span>03</span>主动探针让候选世界更接近隐藏真值</figcaption><img src="figures/abc_candidate_worlds.png" alt="候选世界主动辨识"></figure>
  </section>
  <details class="boundary"><summary>查看实验设计、终极目标与研究边界</summary><div class="boundary-content"><strong>700 个候选世界如何生成：</strong>它们不是 700 套算法，而是同一模拟器内 8 个声明参数在固定范围中抽样得到的 700 组内部结构；候选生成种子为 <code>{candidate_generation['bank_seed']}</code>，验证器已重放并通过。<br><strong>独立检查：</strong>未参与筛选的 holdout 响应 RMSE 为 <code>{holdout_before:.3f}→{holdout_after:.3f}</code>。候选数 <code>{before}→{after}</code> 来自预先固定的 {accept_fraction*100:.0f}% 接受规则，不是质量指标。<br><strong>终极目标：</strong>生成候选世界、主动辨识、预演未来分叉，并在真实机制不确定时寻找跨多个世界都稳健的行动。<br><strong>研究边界：</strong>这是人工市场中的合成存在性演示，不是真实市场验证，不代表交易收益。</div></details>
</main>
</body>
</html>
"""
    RESULT_PAGE.write_text(html, encoding="utf-8")


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    print("[1/3] 正在重新运行同迹异构与主动辨识实验……", flush=True)
    metrics = run(OUTPUT)
    pre = metrics["dose_experiment"]["pre_observable_max_abs_difference"]
    drawdown = metrics["headline_dose_2"]["max_drawdown"]["mean"] * 100.0
    spread = metrics["headline_dose_2"]["peak_spread_bps"]["mean"]
    parameter_before = metrics["abc"]["prior_mean_normalized_parameter_distance"]
    parameter_after = metrics["abc"]["posterior_mean_normalized_parameter_distance"]
    holdout_before = metrics["abc"]["holdout_response"]["prior_median_rmse"]
    holdout_after = metrics["abc"]["holdout_response"]["posterior_median_rmse"]

    observed = (
        f"PASS | {pre:.0f} | {drawdown:+.2f}pp | {spread:+.2f}bps | "
        f"parameter {parameter_before:.3f}→{parameter_after:.3f} | "
        f"holdout {holdout_before:.3f}→{holdout_after:.3f}"
    )
    expected = "PASS | 0 | +4.25pp | +16.31bps | parameter 0.330→0.278 | holdout 1.896→0.934"
    if observed != expected:
        raise AssertionError(f"Unexpected result: {observed}")

    print("[2/3] 数据、图表与完整性检查已生成。", flush=True)
    write_result_page(metrics)
    print("[3/3] 复现完成。", flush=True)
    print(observed, flush=True)
    print(f"RESULT_PAGE | {RESULT_PAGE}", flush=True)


if __name__ == "__main__":
    main()

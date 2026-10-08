from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


PACK = Path(__file__).resolve().parent
CODE = PACK / "code"
OUTPUT = PACK / "robustness_reproduced"
RESULT_PAGE = OUTPUT / "打开查看稳健性结果.html"
sys.path.insert(0, str(CODE))

from marketgenesis_robustness import run  # noqa: E402


def write_result_page(report: dict) -> None:
    drawdown = report["dose_2_drawdown_difference_pp"]
    spread = report["dose_2_peak_spread_difference_bps"]
    parameter = report["abc_parameter_distance_relative_reduction"]
    holdout = report["abc_holdout_response_relative_reduction"]
    payload = {
        "status": "PASS" if report["passed_all_predeclared_gates"] else "FAIL",
        "protocol_version": report["protocol_version"],
        "n_seed_batches": report["design"]["n_seed_batches"],
        "replicates_per_seed_batch": report["design"]["replicates_per_seed_batch"],
        "paired_paths_per_dose_total": report["design"]["paired_paths_per_dose_total"],
        "drawdown_positive_batches": drawdown["positive_batch_count"],
        "spread_positive_batches": spread["positive_batch_count"],
        "parameter_improved_batches": parameter["positive_batch_count"],
        "holdout_improved_batches": holdout["positive_batch_count"],
        "candidate_world_generation": report["candidate_world_generation"],
        "acceptance_design": report["acceptance_design"],
        "implementation_boundary": report["implementation_boundary"],
        "same_simulator_family_only": True,
    }
    (OUTPUT / "稳健性结果摘要.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MarketGenesis · 多种子稳健性复现</title>
<style>
:root{{--navy:#102d49;--blue:#1d649c;--red:#b82a30;--gray:#66717d;--light:#f4f7f9}}
*{{box-sizing:border-box}} body{{margin:0;background:#edf2f5;color:var(--navy);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{width:min(1180px,92vw);margin:36px auto 72px}} .hero,.panel{{background:#fff;border-radius:24px;box-shadow:0 18px 48px rgba(16,45,73,.10)}}
.hero{{padding:34px}} h1{{margin:8px 0;font-size:clamp(30px,5vw,52px)}} .sub{{color:var(--gray);font-size:18px;line-height:1.7}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:24px}} .card{{background:var(--light);border-radius:16px;padding:18px}}
.number{{display:block;font-size:30px;font-weight:850;color:var(--blue)}} .label{{display:block;margin-top:6px;color:var(--gray);line-height:1.45}}
.panel{{margin-top:22px;padding:22px}} .panel img{{width:100%;display:block;border-radius:12px}} .boundary{{margin-top:22px;background:#fff7f7;border-left:5px solid var(--red);padding:18px 22px;border-radius:12px;line-height:1.7}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<section class="hero"><div style="color:var(--red);font-weight:800;letter-spacing:.12em">MARKETGENESIS · MULTI-SEED</div>
<h1>20 组预先固定根种子：全部门槛通过</h1>
<p class="sub">每组 320 次配对续跑，共 {report['design']['paired_paths_per_dose_total']} 对路径/剂量；20 组全部保留。区间以“根种子组”为重抽样单位。</p>
<div class="cards">
<div class="card"><span class="number">{drawdown['positive_batch_count']}/{drawdown['total_batch_count']}</span><span class="label">dose=2 最大回撤效应同向</span></div>
<div class="card"><span class="number">{spread['positive_batch_count']}/{spread['total_batch_count']}</span><span class="label">dose=2 峰值价差效应同向</span></div>
<div class="card"><span class="number">{parameter['positive_batch_count']}/{parameter['total_batch_count']}</span><span class="label">探针后参数距离改善</span></div>
<div class="card"><span class="number">{holdout['positive_batch_count']}/{holdout['total_batch_count']}</span><span class="label">独立 holdout RMSE 改善</span></div>
</div></section>
<section class="panel"><img src="figures/multiseed_dose_forest.png" alt="多根种子森林图"></section>
<section class="panel"><img src="figures/multiseed_dose_response.png" alt="跨根种子剂量响应"></section>
<section class="panel"><img src="figures/multiseed_abc_quality.png" alt="主动探针质量"></section>
<div class="boundary"><strong>候选来源：</strong>每一组根种子都在同一模拟器中，对 8 个声明参数抽样 700 个候选世界；20 组共保留 {report['design']['candidate_world_records_total']:,} 条候选记录。<code>700→70</code> 是固定 10% 接受规则，不是实验成绩。<br><strong>解释边界：</strong>这说明结论不是固定根种子 <code>20260830</code> 的偶然，但仍只是在同一个人工模拟器家族内检验随机抽样稳定性；它不等于跨模型稳健性、真实市场验证或实体机器人验证。</div>
</main></body></html>"""
    RESULT_PAGE.write_text(html, encoding="utf-8")


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    print("[1/3] 运行 20 组根种子；通常需要 3—6 分钟，请不要关闭窗口……", flush=True)
    report = run(OUTPUT)
    drawdown = report["dose_2_drawdown_difference_pp"]
    spread = report["dose_2_peak_spread_difference_bps"]
    parameter = report["abc_parameter_distance_relative_reduction"]
    holdout = report["abc_holdout_response_relative_reduction"]
    if not report["passed_all_predeclared_gates"]:
        raise AssertionError("预先固定的科学门槛未全部通过；请查看 multiseed_report.json")
    print("[2/3] 多种子数据、图表与完整性检查已生成。", flush=True)
    write_result_page(report)
    print("[3/3] 稳健性复现完成。", flush=True)
    print(
        f"PASS | main effects {drawdown['positive_batch_count']}/{drawdown['total_batch_count']} & "
        f"{spread['positive_batch_count']}/{spread['total_batch_count']} | "
        f"parameter {parameter['positive_batch_count']}/{parameter['total_batch_count']} | "
        f"holdout {holdout['positive_batch_count']}/{holdout['total_batch_count']}",
        flush=True,
    )
    print(f"RESULT_PAGE | {RESULT_PAGE}", flush=True)


if __name__ == "__main__":
    main()

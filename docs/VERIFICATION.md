# 本地公开版验证记录

验证日期：2026-10-08。环境：macOS，Python 3.12.14；numpy 2.3.5、pandas 2.2.3、Pillow 12.3.0。

## 实际执行

```bash
python reproduce.py
python robustness_reproduce.py
python verify.py --reproduced --multiseed
```

固定种子与 20 根种子实验均重新计算，退出状态为 0。

```text
Fixed: PASS | 0 | +4.25pp | +16.31bps | parameter 0.330→0.278 | holdout 1.896→0.934
20 roots: PASS | main effects 20/20 & 20/20 | parameter 18/20 | holdout 18/20
Fixed reference data: 7/7 CSV/JSON byte-identical
Multi-root reference data: 8/8 CSV/JSON byte-identical
Fixed integrity checks: 19/19
Multi-root integrity checks: 15/15
Multi-root scientific gates: 10/10
```

参考文件自身的 21 项 SHA-256 检查全部通过。六张新生成 PNG 与参考图的文件哈希不相同：字体渲染有差异，ABC 图还调整了标签位置。数值不变，新图各自的完整性清单通过；不要求不同平台像素完全相同。

关键数据的 SHA-256：

```text
8f336765a62ddae5694766f455208bf63c66fb24cf7632e65bb862e2bd385231  experiment_metrics.json
eebe0360ffa186d349a49213c2a2c0fd46c83ddfa7640297484fa1355ccd4910  multiseed_report.json
dd9f41c0f557a07ed4ac969385fdb464d9d50ce6eda659b0ed4a32b1062d4ec8  multiseed_abc_candidates.csv
```

生成目录未重复纳入 Git；请运行入口自行生成。GitHub Actions 已配置为 Linux / Python 3.12 的固定种子复现检查，但本记录不是远程 CI 通过证明；远程状态应以仓库 Actions 页面为准。

## 展示材料

三份 PDF 的私人联系方式与元数据已移除，受影响页面已渲染检查。原始视频保留不变，逐字节校验通过；该历史视频中的网页界面包含 LIVE EVIDENCE 字样，实际展示为参考数据动画，当前公开网页和 README 已明确解释，不将动画视为实时计算。

原视频 SHA-256：

```text
f23107f6ba28cd67c85a385fcbe0663f6d1fb91f641255d9fb3a12ccc9e41d59
```

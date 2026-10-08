# 零基础复现说明

Mac 和 Windows 提供双击入口；Linux 可使用下方的终端命令。建议使用 Python 3.12，与自动复现工作流一致。

## 先做：固定种子数据精确复现

1. 下载并解压整个仓库，保持文件夹完整，不要只移动其中一个文件。
2. Mac 双击 `RUN_FIXED_SEED_MAC.command`；Windows 双击 `RUN_FIXED_SEED_WINDOWS.bat`。
3. 如果系统提示无法验证或阻止打开：关闭提示，右键该文件，再选择“打开”。
4. 第一次运行需要联网安装 `numpy`、`pandas` 和 `Pillow`，可能需要 1—5 分钟。
5. 看到 `PASS | 0 | +4.25pp | +16.31bps | parameter 0.330→0.278 | holdout 1.896→0.934` 后即为复现成功。
6. 浏览器会自动打开 `reproduced/打开查看结果.html`，三张新图也在 `reproduced/figures/`。

以后再次运行时，安装步骤通常只需几秒，实验本身约 10—30 秒。

这一步的含义是：同一套代码、同一个随机种子，能够重新算出提交时的同一结果。

## 再做：20 根种子稳健性实验

1. Mac 双击 `RUN_MULTI_SEED_MAC.command`；Windows 双击 `RUN_MULTI_SEED_WINDOWS.bat`。
2. 等待 3—6 分钟；窗口中会依次显示 20 组根种子的进度，请不要关闭。
3. 看到 `PASS | main effects 20/20 & 20/20 | parameter 18/20 | holdout 18/20` 后完成。
4. 浏览器会打开 `robustness_reproduced/打开查看稳健性结果.html`。

这一步不要求再次得到恰好 `+4.25pp`，而是检查结论换一批随机路径后是否仍保持方向。它回答的是“不是某一个种子的偶然吗”，不是“真实市场一定如此吗”。

## 如何证明这是刚刚重新跑出来的

- 运行前可以暂时把旧的 `reproduced/` 移到别处；程序本身也会在每次运行时重新创建该目录。
- 运行结束后，在访达中查看 `reproduced/figures/` 的“修改日期”。
- `reproduced/复现结果摘要.json` 保存本次运行的四项数字。
- `reproduced/validation_report.json` 的 `passed` 应为 `true`。
- 多种子运行结束后，`robustness_reproduced/validation_report.json` 的 `passed` 也应为 `true`，并且 `data/multiseed_report.json` 中 `passed_all_predeclared_gates` 应为 `true`。

## 终端复现与独立核对（Mac / Linux）

在仓库根目录打开终端，执行：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python verify.py
.venv/bin/python reproduce.py
.venv/bin/python verify.py --reproduced
```

需要复跑 20 组根种子时，继续执行：

```sh
.venv/bin/python robustness_reproduce.py
.venv/bin/python verify.py --reproduced --multiseed
```

Windows 终端将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。命令行不会自动打开页面，请自行打开输出目录中的 HTML。`verify.py` 不执行模拟或改写文件：它检查参考文件 SHA-256、固定种子完整性，并在指定复现目录后比较 CSV/JSON 数据。跨平台比较使用 `rtol=1e-10, atol=1e-12`，同时报告字节完全一致的文件数量；字体造成的图像像素差异不作为数值复现失败。

`demo.html` 是内嵌参考数据的交互回放，按钮展示已有轨迹与指标，不在浏览器中运行实验。重新计算请使用上述 Python 入口。

## 常见问题

### 提示“未找到 Python 3”

前往 <https://www.python.org/downloads/> 安装适合系统的 Python 3.12，安装后重新双击。

### 依赖安装失败

通常是网络问题。切换网络后再运行，不要删除终端中的报错；截图可以用于定位问题。

### 图里的中文显示异常

程序会优先使用 macOS 自带的中文字体。若在极少数系统上仍显示异常，数字、数据和验证结果不受影响。

### 我能否修改代码后仍得到 PASS

可以修改，但修改后的结果不再等同于提交版本。对外展示时请保留原始压缩包，并公开随机种子和依赖版本。

### 为什么不再把 700→70 当作核心结果

因为 70 是代码预先写死的 10% 接受比例。真正需要检查的是：探针后候选世界离合成真值是否更近，以及没有参与筛选的独立 holdout 响应误差是否下降。

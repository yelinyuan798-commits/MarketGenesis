#!/bin/zsh

set -u

PACKAGE_DIR=${0:A:h}
cd "$PACKAGE_DIR" || exit 1

clear
echo "============================================================"
echo " MarketGenesis · 20 根种子稳健性实验"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3。请先安装 Python 3 后重试。"
  read "reply?按回车键关闭……"
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[准备] 第一次运行：正在创建独立环境……"
  if ! python3 -m venv .venv; then
    echo "创建 Python 环境失败。"
    read "reply?按回车键关闭……"
    exit 1
  fi
fi

echo "[准备] 正在检查固定版本依赖；第一次运行需要联网。"
if ! .venv/bin/python -m pip install --disable-pip-version-check --quiet -r requirements.txt; then
  echo "依赖安装失败。请检查网络后重试。"
  read "reply?按回车键关闭……"
  exit 1
fi

echo "[运行] 20 组 × 320 次；通常需要 3—6 分钟，请不要关闭窗口。"
echo
if ! .venv/bin/python robustness_reproduce.py; then
  echo "稳健性实验未通过。请保留本窗口和输出目录。"
  read "reply?按回车键关闭……"
  exit 1
fi

open "$PACKAGE_DIR/robustness_reproduced/打开查看稳健性结果.html"
echo
read "reply?按回车键关闭本窗口……"

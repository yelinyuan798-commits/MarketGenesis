#!/bin/zsh

set -u

PACKAGE_DIR=${0:A:h}
cd "$PACKAGE_DIR" || exit 1

clear
echo "============================================================"
echo " MarketGenesis · Mac 一键复现"
echo "============================================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3。"
  echo "请先从 https://www.python.org/downloads/macos/ 安装 Python 3，"
  echo "安装完成后重新双击本文件。"
  echo
  read "reply?按回车键关闭……"
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[准备] 第一次运行：正在创建独立环境……"
  if ! python3 -m venv .venv; then
    echo "创建 Python 环境失败。请把本窗口截图发给项目作者。"
    read "reply?按回车键关闭……"
    exit 1
  fi
fi

echo "[准备] 正在检查三个固定版本的依赖；第一次运行需要联网。"
if ! .venv/bin/python -m pip install --disable-pip-version-check --quiet -r requirements.txt; then
  echo
  echo "依赖安装失败。请检查网络后重试，并把本窗口截图保留。"
  read "reply?按回车键关闭……"
  exit 1
fi

echo "[运行] 环境已就绪，实验通常在 10—30 秒内完成。"
echo
if ! .venv/bin/python reproduce.py; then
  echo
  echo "复现未通过。请保留本窗口，不要修改输出。"
  read "reply?按回车键关闭……"
  exit 1
fi

echo
echo "成功：浏览器将打开刚刚由本机生成的结果页面。"
open "$PACKAGE_DIR/reproduced/打开查看结果.html"
echo
read "reply?按回车键关闭本窗口……"

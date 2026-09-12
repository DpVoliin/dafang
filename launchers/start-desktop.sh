#!/usr/bin/env bash
# Linux：双击或终端运行本文件即可启动桌面版
cd "$(dirname "$0")/.." || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "没有找到 Python 3.9+，请先安装（如 sudo apt install python3）"
  read -r -p "按回车关闭…" _
  exit 1
fi
exec "$PY" dafang.py --desktop

#!/bin/bash
# macOS：双击本文件即可启动桌面版（首次可能需要右键 → 打开）
cd "$(dirname "$0")/.." || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  osascript -e 'display alert "没有找到 Python" message "请先安装 Python 3.9+：https://www.python.org/downloads/"'
  exit 1
fi
exec "$PY" dafang.py --desktop

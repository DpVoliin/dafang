#!/bin/sh
# 大大方方 Agent · 卸载（macOS / Linux）
cd "$(dirname "$0")/.." || exit 1
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
"$PY" uninstall.py "$@"
exit $?

#!/bin/sh
# 大大方方 Agent · 自检（不需要模型/联网）
cd "$(dirname "$0")/.." || exit 1
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
"$PY" dafang.py --selftest
exit $?

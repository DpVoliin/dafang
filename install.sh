#!/usr/bin/env bash
# 大大方方 Agent 一键安装（Linux / systemd）。
# 用法：  bash install.sh          # 安装到 ~/dafang 并注册 systemd 服务
#         bash install.sh --no-service   # 只准备目录，不注册服务
set -e
DIR="${DAFANG_DIR:-$HOME/dafang}"
PORT="${DAFANG_PORT:-11439}"

echo "== 大大方方 Agent 安装 =="
command -v python3 >/dev/null || { echo "需要 python3（3.9+）"; exit 1; }
python3 -c 'import sys; assert sys.version_info>=(3,9), sys.version' || { echo "python 版本过低"; exit 1; }

mkdir -p "$DIR" "$HOME/.dafang"
if [ -f "$(dirname "$0")/dafang.py" ]; then
  cp "$(dirname "$0")/dafang.py" "$DIR/dafang.py"
fi
[ -f "$DIR/dafang.py" ] || { echo "没找到 dafang.py，请把本脚本和 dafang.py 放同一目录"; exit 1; }

# 先用非特权端口做一次冒烟测试，确认能起来
echo "· 冒烟测试…"
DAFANG_PORT="$PORT" nohup python3 "$DIR/dafang.py" >/tmp/dafang-smoke.log 2>&1 &
SMOKE=$!
sleep 2
CODE=$(curl -s -o /dev/null -m5 -w '%{http_code}' "http://127.0.0.1:$PORT/" || true)
kill $SMOKE 2>/dev/null || true
if [ "$CODE" != "200" ]; then
  echo "  ❌ 起不来，日志："; tail -5 /tmp/dafang-smoke.log; exit 1
fi
echo "  ✅ 启动正常（HTTP $CODE）"

if [ "$1" = "--no-service" ]; then
  echo "完成。手动启动： DAFANG_PORT=$PORT python3 $DIR/dafang.py"
  exit 0
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "没有 systemd。手动启动： DAFANG_PORT=$PORT python3 $DIR/dafang.py"
  exit 0
fi

UNIT="$HOME/.config/systemd/user/dafang.service"
mkdir -p "$(dirname "$UNIT")"
sed -e "s#%h/dafang#$DIR#g" -e "s#DAFANG_PORT=11439#DAFANG_PORT=$PORT#" \
    "$(dirname "$0")/deploy/dafang.service" > "$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now dafang
sleep 2
echo "服务状态： $(systemctl --user is-active dafang)"
echo
echo "打开： http://127.0.0.1:$PORT"
echo "日志： journalctl --user -u dafang -f    （或 tail -f ~/.dafang/dafang.log）"
echo
echo "想开机即启（不需登录）： sudo loginctl enable-linger $USER"

# ── 可选：桌面版（只绑 127.0.0.1，像正常软件那样用） ──────────────────────
if [ "$1" = "--desktop" ] || [ "$2" = "--desktop" ]; then
  echo
  echo "== 桌面版 =="
  if [ -d "$HOME/.local/share/applications" ] && [ -f "$(dirname "$0")/launchers/dafang.desktop" ]; then
    sed "s#\$PWD#$DIR#g" "$(dirname "$0")/launchers/dafang.desktop" \
      > "$HOME/.local/share/applications/dafang.desktop"
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    echo "已加入应用菜单（搜「大大方方」即可）"
  fi
  echo "命令行启动： python3 $DIR/dafang.py --desktop"
fi
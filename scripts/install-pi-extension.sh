#!/usr/bin/env bash
# ssot-kit · 安装/卸载 Pi 扩展（开机注入 + 回忆触发检索）
# 用法: bash scripts/install-pi-extension.sh [--dry] [--uninstall] [--dir DIR] [--root DIR]
# 默认 dir = ~/.pi/agent/extensions；ROOT = $SSOT_ROOT 或 ~/ssot（写进扩展的默认根）
# 行为：复制（非 symlink，便于随 kit 升级覆盖）；已存在则备份为 <name>.bak-<ts>；--dry 不落盘。
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
DIR="${HOME}/.pi/agent/extensions"
DRY=0
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --dir) DIR="$2"; shift 2 ;;
    --root) ROOT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done
KIT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${DIR/#\~/$HOME}"
ROOT="${ROOT/#\~/$HOME}"
NAME="ssot-boot.ts"
SRC="$KIT/hooks/pi/$NAME"
DST="$DIR/$NAME"

if [ ! -f "$SRC" ]; then
  echo "❌ kit 内缺 $SRC"; exit 1
fi

if [ "$UNINSTALL" = "1" ]; then
  if [ -f "$DST" ]; then
    if [ "$DRY" = "1" ]; then
      echo "（dry）将移除 $DST"
    else
      rm -f "$DST"
      echo "✅ 已移除 $DST"
    fi
  else
    echo "（无 $DST，跳过）"
  fi
  exit 0
fi

if [ "$DRY" = "1" ]; then
  echo "（dry）将复制 $SRC → $DST"
  echo "（dry）扩展默认 ROOT=$ROOT（可用 SSOT_ROOT 覆盖）"
  exit 0
fi

mkdir -p "$DIR"
if [ -f "$DST" ]; then
  BAK="$DST.bak-$(date +%Y%m%d-%H%M%S)"
  cp -p "$DST" "$BAK"
  echo "  备份: $BAK"
fi
cp -f "$SRC" "$DST"
echo "✅ 扩展已安装 → $DST"

echo
echo "下一步（见 docs/HOOKS.md §七）："
echo "  1) 用户级入口 ~/.pi/agent/AGENTS.md 加 SSOT 指针（见 SETUP.md；本脚本不改它）"
echo "  2) 已装 skill 根：把 ssot-ops 放进 ~/.pi/agent/skills（不要启用 ~/.agents/skills，避免双根重名）"
echo "  3) 验证：SSOT_PI_VERBOSE=1 pi -p --no-session --no-tools \"把上下文中以 [SSOT] 开头的行原样输出\""
echo "     日志：~/.cache/ssot-pi-boot/debug.log ｜ 开关：SSOT_PI_BOOT=0 / SSOT_PI_RECALL=0"

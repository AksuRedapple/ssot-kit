#!/usr/bin/env bash
# ssot · 下游升级（只 pull 场景，2026-10-31 回迁）
# 用法: bash tools/install/update.sh [--root DIR] [--dry] [--skip-pull]
# 行为: git pull --ff-only → 应用框架件 → 跑迁移(若有) → 自检
set -euo pipefail

ROOT="$HOME/ssot"; DRY=0; SKIP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --root)      ROOT="$2"; shift 2 ;;
    --dry)       DRY=1; shift ;;
    --skip-pull) SKIP=1; shift ;;
    -h|--help)   sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "── ssot 升级（仓库 $KIT → 实例 ${ROOT}）"

if [ "$SKIP" = 0 ] && [ -d "$KIT/.git" ] && git -C "$KIT" remote get-url origin >/dev/null 2>&1; then
  if [ "$DRY" = 1 ]; then echo "   [dry] git pull --ff-only"; else
    git -C "$KIT" pull --ff-only || { echo "❌ git pull 失败，停止（实例未改动）"; exit 1; }
  fi
else
  echo "   跳过 pull（无 origin 或 --skip-pull）"
fi

# 框架件同步(工具/钩子)
[ "$DRY" = 1 ] || mkdir -p "$ROOT/tools/hooks"
for f in "$KIT"/tools/*.py; do
  [ -e "$f" ] || continue
  [ "$DRY" = 1 ] || cp -f "$f" "$ROOT/tools/"
done
# 共享层 ssotlib/（tools/ 就是运行目录，工具 import 它不需要注入路径）
if [ -d "$KIT/tools/ssotlib" ]; then
  [ "$DRY" = 1 ] || { mkdir -p "$ROOT/tools/ssotlib"; cp -f "$KIT"/tools/ssotlib/*.py "$ROOT/tools/ssotlib/"; }
fi
for f in "$KIT"/hooks/*.sh; do
  [ -e "$f" ] || continue
  [ "$DRY" = 1 ] || cp -f "$f" "$ROOT/tools/hooks/"
done
if [ -f "$KIT/tools/serve_embed.sh" ]; then
  [ "$DRY" = 1 ] || cp -f "$KIT/tools/serve_embed.sh" "$ROOT/tools/serve_embed.sh"
  [ "$DRY" = 1 ] || chmod +x "$ROOT/tools/serve_embed.sh"
fi
echo "   框架件已同步"
if [ -f "$KIT/instance/gitignore" ] && [ ! -f "$ROOT/.gitignore" ]; then
  [ "$DRY" = 1 ] || cp "$KIT/instance/gitignore" "$ROOT/.gitignore"
  echo "   + 实例 .gitignore"
fi

if [ -f "$KIT/tools/sp_migrate.py" ]; then
  if [ "$DRY" = 1 ]; then echo "   [dry] python3 tools/sp_migrate.py --to current"; else
    python3 "$KIT/tools/sp_migrate.py" --to current || { echo "❌ 迁移失败，停止"; exit 1; }
  fi
else
  echo "   无 sp_migrate.py（跳过数据迁移）"
fi

if [ -f "$ROOT/tools/ssot_check.py" ]; then
  if [ "$DRY" = 1 ]; then echo "   [dry] python3 tools/ssot_check.py"; else
    python3 "$ROOT/tools/ssot_check.py" | tail -5 || true
  fi
fi
echo "✅ 升级完成"

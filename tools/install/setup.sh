#!/usr/bin/env bash
# ssot · 首装（2026-10-31 回迁自 kit，多 harness 版）
# 用法: bash tools/install/setup.sh [--root DIR] [--skills-dir DIR] [--dry]
# 行为: 建骨架目录 → 补缺模板 → 分发技能（幂等；已存在的文件绝不覆盖）
set -euo pipefail

ROOT="$HOME/ssot"; SKILLS=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --root)       ROOT="$2"; shift 2 ;;
    --skills-dir) SKILLS="$2"; shift 2 ;;
    --dry)        DRY=1; shift ;;
    -h|--help)    sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done
KIT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -z "$SKILLS" ]; then
  for d in "$HOME/.qoder" "$HOME/.dsh" "$HOME/.claude" "$HOME/.codex" "$HOME/.local/share/opencode"; do
    if [ -d "$d" ]; then SKILLS="$d/skills"; break; fi
  done
fi

echo "── ssot 首装 → $ROOT"
echo "   仓库: $KIT"
echo "   技能目标: ${SKILLS:-（未探测到 harness，跳过技能）}"
[ "$DRY" = 1 ] && echo "   [dry] 只打印不落盘"

DIRS="inbox knowledge knowledge/topics lines profile sessions compile logs alerts backups tools/hooks"
for d in $DIRS; do
  if [ "$DRY" = 1 ]; then echo "   + $d/"; else mkdir -p "$ROOT/$d"; fi
done

# 框架件:工具脚本(覆盖式同步)
[ "$DRY" = 1 ] || mkdir -p "$ROOT/tools/hooks"
for f in "$KIT"/tools/*.py; do
  [ -e "$f" ] || continue
  [ "$DRY" = 1 ] || cp -f "$f" "$ROOT/tools/"
done
for f in "$KIT"/hooks/*.sh; do
  [ -e "$f" ] || continue
  [ "$DRY" = 1 ] || cp -f "$f" "$ROOT/tools/hooks/"
done
echo "   工具: $(ls "$ROOT"/tools/*.py 2>/dev/null | wc -l | tr -d ' ') 个"

# 模板只补缺
n=0
if [ -d "$KIT/instance" ]; then
  while IFS= read -r f; do
    rel="${f#$KIT/instance/}"
    if [ ! -f "$ROOT/$rel" ]; then
      n=$((n+1))
      if [ "$DRY" = 0 ]; then mkdir -p "$(dirname "$ROOT/$rel")"; cp "$f" "$ROOT/$rel"; fi
      echo "   + 模板 $rel"
    fi
  done < <(find "$KIT/instance" -type f 2>/dev/null)
fi

# 技能分发（只补缺）
m=0
if [ -n "$SKILLS" ] && [ -d "$KIT/skills" ]; then
  for d in "$KIT/skills"/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    if [ ! -f "$SKILLS/$name/SKILL.md" ]; then
      m=$((m+1))
      if [ "$DRY" = 0 ]; then mkdir -p "$SKILLS/$name"; cp -f "$d/SKILL.md" "$SKILLS/$name/SKILL.md"; fi
    fi
  done
  echo "   技能: 新增 $m 个 → $SKILLS"
fi
echo "✅ 完成（模板补缺 $n 个）"

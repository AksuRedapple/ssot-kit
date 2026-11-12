#!/usr/bin/env bash
# ssot-kit · 维护者发布：把已配置的 SSOT_ROOT 框架件同步进本仓库 → commit → push
# 白名单制：只发布清单内的框架件；内容层永不发布。
# 用法: bash scripts/publish.sh [--dry] ["提交说明"]
set -euo pipefail

DRY=0
if [ "${1:-}" = "--dry" ]; then DRY=1; shift; fi
MSG="${1:-sync framework $(date +%F)}"

KIT="$(cd "$(dirname "$0")/.." && pwd)"
SSOT="${SSOT_ROOT:-$HOME/ssot}"

if [ ! -f "$SSOT/tools/kit_check.py" ]; then
  echo "❌ 此脚本是维护者工作流：请把 SSOT_ROOT 指向包含 kit_check.py 的私有实例" >&2
  exit 2
fi

HARD_BAN='/Users/'
EXTRA_BAN="${SSOT_KIT_EXTRA_BAN:-}"
BAN="$HARD_BAN${EXTRA_BAN:+|$EXTRA_BAN}"

echo "── manifest 同步（kit_manifest.json 是唯一白名单）"
if [ "$DRY" = "1" ]; then
  echo "  （dry）将按 manifest 同步 ${KIT}（不写盘）"
else
  python3 "$SSOT/tools/kit_check.py" --sync --kit "$KIT" || {
    echo "❌ manifest 同步失败"; exit 1;
  }
fi
python3 "$SSOT/tools/kit_check.py" --kit "$KIT" || {
  echo "❌ 子集核验失败"; exit 1;
}

echo "── 防泄漏复查（第二层闸：全树禁词扫描；扩展词由 SSOT_KIT_EXTRA_BAN 注入）"
HITS="$(find "$KIT/tools" "$KIT/skills" "$KIT/instance" "$KIT/docs" \
  "$KIT/README.md" "$KIT/SETUP.md" "$KIT/UPGRADE.md" "$KIT/CHANGELOG.md" "$KIT/CAPABILITIES.md" \
  -type f ! -path '*/__pycache__/*' ! -name '*.pyc' -print0 2>/dev/null \
  | xargs -0 grep -n -iE "$BAN" 2>/dev/null || true)"
if [ -n "$HITS" ]; then
  echo "$HITS"
  echo "❌ 禁词命中——中止发布，先清理"; exit 1
fi
echo "  ✓ 0 命中"

if [ "$DRY" = "1" ]; then
  echo "（dry 模式：不 commit / 不 push）"; exit 0
fi

cd "$KIT"
git add -A
if git diff --cached --quiet; then
  echo "无变更，无需发布"; exit 0
fi
# 发布闸门：影子实例 dogfood（无 FORCE 时必跑）
if [ "${FORCE:-0}" != "1" ]; then
  echo "── preflight（影子实例 dogfood）"
  bash "$(dirname "$0")/preflight.sh" --quiet || { echo "❌ preflight 红，拒绝发布（FORCE=1 可绕过，需记日志）"; exit 1; }
fi
# 四数自检:VERSION / CHANGELOG / 同步件一致
V=$(tr -d '\n' < "$(dirname "$0")/../VERSION")
bash "$(dirname "$0")/release-check.sh" || { echo "❌ release metadata 不一致"; exit 1; }
GIT_AUTHOR_NAME=mac-agent GIT_AUTHOR_EMAIL=mac@local GIT_COMMITTER_NAME=mac-agent GIT_COMMITTER_EMAIL=mac@local \
  git commit -q -m "$MSG"
git push origin HEAD
echo "✅ 已发布: $(git log --oneline -1)"

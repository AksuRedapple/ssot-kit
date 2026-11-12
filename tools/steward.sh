#!/usr/bin/env bash
# ssot-kit · 6h 值守（通用版）：索引增量 + 自查 + 草稿计数，只写本实例。
# 用法：bash tools/steward.sh   （由 scripts/install-steward.sh 挂 launchd/systemd timer）
# 可选：SSOT_STEWARD_SKIP_INDEX=1 跳过索引（无嵌入服务/测试时）
set -u

ROOT="${SSOT_ROOT:-$HOME/ssot}"
LOG="$ROOT/alerts/steward.log"
mkdir -p "$ROOT/alerts" "$ROOT/sessions/_pending" 2>/dev/null || true

say() { echo "$(date '+%F %T') $1" >> "$LOG"; }
say "== steward begin =="

if [ "${SSOT_STEWARD_SKIP_INDEX:-0}" = "1" ]; then
  say "index: skipped（SSOT_STEWARD_SKIP_INDEX=1）"
elif [ -f "$ROOT/tools/sp_index.py" ] && curl -s -m 3 http://127.0.0.1:8399/health >/dev/null 2>&1; then
  LINE=$(cd "$ROOT" && python3 tools/sp_index.py --incremental 2>&1 | tail -1)
  say "index: ${LINE}"
else
  say "index: skipped（8399 不在或 sp_index.py 缺失）"
fi

if [ -f "$ROOT/tools/ssot_check.py" ]; then
  CHECK=$(cd "$ROOT" && python3 tools/ssot_check.py --root "$ROOT" \
    --report "$ROOT/SSOT_REPORT.md" 2>&1 | tail -1)
  say "check: ${CHECK}"
  say "report: SSOT_REPORT.md"
fi

DRAFTS=$(find "$ROOT/sessions/_pending" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
say "pending drafts: ${DRAFTS}"
say "== steward done =="

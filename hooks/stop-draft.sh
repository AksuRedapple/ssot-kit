#!/usr/bin/env bash
mkdir -p "${ROOT:-$HOME/ssot}/alerts" 2>/dev/null || true
# ssot-kit · Stop hook：只写「机械草稿」，不做语义判断。
# 同 sid 默认 600 秒去抖（Stop 每轮都会触发，不能每轮写一行）；草稿供收尾/周值班转 registry。
# 关停：touch $ROOT/.stop-draft-off（或 SSOT_STOP_DRAFT_OFF=1）
set -u

ROOT="${SSOT_ROOT:-$HOME/ssot}"
[ -f "$ROOT/.stop-draft-off" ] && exit 0
[ "${SSOT_STOP_DRAFT_OFF:-0}" = "1" ] && exit 0

IN=$(cat)
PARSED=$(printf '%s' "$IN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    sid = d.get('session_id') or d.get('sessionId') or '-'
    cwd = d.get('cwd') or '-'
    side = '1' if d.get('isSidechain') else '0'
    print(f'{sid}|{cwd}|{side}')
except Exception:
    print('-|-|0')" 2>>"$ROOT/alerts/hook.err")
IFS='|' read -r SID CWD SIDE <<< "${PARSED:--|-|0}"
[ "$SIDE" = "1" ] && exit 0
[ -z "$SID" ] || [ "$SID" = "-" ] && exit 0

SID8=$(printf '%s' "$SID" | tr -cd 'A-Za-z0-9-' | cut -c1-8)
[ -z "$SID8" ] && exit 0
CWD=$(printf '%s' "$CWD" | tr '\t\n|' '   ')

DEBOUNCE="${SSOT_DRAFT_DEBOUNCE:-600}"
STATE="$ROOT/sessions/.draft-state"
PENDING="$ROOT/sessions/_pending"
MARK="$STATE/$SID8.last"

mtime() { stat -f %m "$1" 2>>"$ROOT/alerts/hook.err" || stat -c %Y "$1" 2>>"$ROOT/alerts/hook.err" || echo 0; }
NOW=$(date +%s)
if [ -f "$MARK" ]; then
  LAST=$(mtime "$MARK")
  [ $((NOW - LAST)) -lt "$DEBOUNCE" ] && exit 0
fi

mkdir -p "$STATE" "$PENDING" 2>>"$ROOT/alerts/hook.err" || exit 0
touch "$MARK" 2>>"$ROOT/alerts/hook.err" || true
FILE="$PENDING/$SID8.md"
if [ ! -f "$FILE" ]; then
  printf '# %s · 收尾草稿（机械事实，待转 registry）\n\n' "$SID8" > "$FILE"
fi
printf -- '- %s | sid: %s | cwd: %s\n' "$(date '+%F %T')" "$SID" "$CWD" >> "$FILE"
exit 0

#!/usr/bin/env bash
set -euo pipefail

SSOT_ROOT="${SSOT_ROOT:-$HOME/ssot}"
PORT="${SSOT_EG2_PORT:-8399}"
LEASE="${SSOT_EG2_LEASE:-/tmp/ssot-eg2.want}"
TIMEOUT="${SSOT_EG2_ACQUIRE_TIMEOUT:-60}"
LIFECYCLE_LOG="${SSOT_EG2_LIFECYCLE_LOG:-$SSOT_ROOT/logs/eg2-lifecycle.jsonl}"
PYTHON="${SSOT_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3
[ "$(uname -s)" = "Darwin" ] || exit 0

log_event() {
  "$PYTHON" - "$LIFECYCLE_LOG" "$1" "$2" "$3" <<'PY' >/dev/null 2>&1 || true
import datetime, json, os, sys
path, event, mode, elapsed = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a', encoding='utf-8') as f:
    f.write(json.dumps({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                        'event': event, 'mode': mode, 'elapsed_s': int(elapsed),
                        'pid': os.getpid()}, ensure_ascii=False) + '\n')
PY
}

health() { curl -fsS -m 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; }

mkdir -p "$(dirname "$LEASE")"
touch "$LEASE"
start=$SECONDS
if health; then
  log_event ready hot 0
  exit 0
fi

log_event acquire cold 0
while [ "$SECONDS" -lt "$TIMEOUT" ]; do
  sleep 0.5
  if health; then
    log_event ready cold "$SECONDS"
    exit 0
  fi
done

log_event acquire_timeout cold "$TIMEOUT"
echo "eg2 acquire: ${TIMEOUT}s 内 :${PORT} 未就绪" >&2
exit 1

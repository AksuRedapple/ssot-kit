#!/usr/bin/env bash
set -euo pipefail

SSOT_ROOT="${SSOT_ROOT:-$HOME/ssot}"
PORT="${SSOT_EG2_PORT:-8399}"
LEASE="${SSOT_EG2_LEASE:-/tmp/ssot-eg2.want}"
TIMEOUT="${SSOT_EG2_ACQUIRE_TIMEOUT:-60}"
LIFECYCLE_LOG="${SSOT_EG2_LIFECYCLE_LOG:-$SSOT_ROOT/logs/eg2-lifecycle.jsonl}"
PYTHON="${SSOT_PYTHON:-$(command -v python3 2>/dev/null || true)}"
[ -n "$PYTHON" ] && [ -x "$PYTHON" ] || PYTHON=/usr/bin/python3
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

health() {
  if [ "${SSOT_EG2_ACQUIRE_DEBUG:-0}" = "1" ]; then
    "$PYTHON" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',int(sys.argv[1]))); s.close()" "$PORT"
  else
    "$PYTHON" -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',int(sys.argv[1]))); s.close()" "$PORT" >/dev/null 2>&1
  fi
}

mkdir -p "$(dirname "$LEASE")"
touch "$LEASE"
start=$SECONDS
if health; then
  log_event ready hot 0
  exit 0
fi

log_event acquire cold 0
i=0
while [ "$i" -lt $((TIMEOUT * 2)) ]; do
  sleep 0.5
  i=$((i + 1))
  if health; then
    log_event ready cold $((i / 2))
    exit 0
  fi
done

log_event acquire_timeout cold "$TIMEOUT"
echo "eg2 acquire: ${TIMEOUT}s 内 :${PORT} 未就绪" >&2
exit 1

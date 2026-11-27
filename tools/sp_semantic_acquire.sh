#!/usr/bin/env bash
set -euo pipefail

SSOT_ROOT="${SSOT_ROOT:-$HOME/ssot}"
LEASE="${SSOT_SEMANTIC_LEASE:-/tmp/ssot-semantic.want}"
SOCKET_PATH="${SSOT_SEMANTIC_SOCKET:-$HOME/.ssot/semantic.sock}"
TIMEOUT="${SSOT_SEMANTIC_ACQUIRE_TIMEOUT:-20}"
LIFECYCLE_LOG="${SSOT_SEMANTIC_LIFECYCLE_LOG:-$SSOT_ROOT/logs/semantic-lifecycle.jsonl}"
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

socket_ready() {
  "$PYTHON" - "$SOCKET_PATH" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    s.connect(sys.argv[1])
finally:
    s.close()
PY
}

mkdir -p "$(dirname "$LEASE")" "$(dirname "$SOCKET_PATH")"
touch "$LEASE"
start=$SECONDS
if socket_ready; then
  log_event ready hot 0
  exit 0
fi

log_event acquire cold 0
while [ "$SECONDS" -lt "$TIMEOUT" ]; do
  sleep 0.25
  if socket_ready; then
    log_event ready cold "$SECONDS"
    exit 0
  fi
done

log_event acquire_timeout cold "$TIMEOUT"
echo "semantic acquire: ${TIMEOUT}s 内 socket 未就绪" >&2
exit 1

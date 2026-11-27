#!/usr/bin/env bash
set -euo pipefail

SSOT_ROOT="${SSOT_ROOT:-$HOME/ssot}"
LABEL="${SSOT_SEMANTIC_LABEL:-com.ssot.semantic}"
LEASE="${SSOT_SEMANTIC_LEASE:-/tmp/ssot-semantic.want}"
STATE_PATH="${SSOT_SEMANTIC_STATE:-/tmp/ssot-semantic.state.json}"
SOCKET_PATH="${SSOT_SEMANTIC_SOCKET:-$HOME/.ssot/semantic.sock}"
IDLE="${SSOT_SEMANTIC_IDLE_SEC:-1800}"
TERM_WAIT="${SSOT_SEMANTIC_TERM_WAIT_SEC:-15}"
# 服务未运行时清理残留租约的年龄阈值，避免删掉 acquire 刚 touch、launchd 尚未拉起的租约。
LEASE_STALE="${SSOT_SEMANTIC_LEASE_STALE_SEC:-120}"
LIFECYCLE_LOG="${SSOT_SEMANTIC_LIFECYCLE_LOG:-$SSOT_ROOT/logs/semantic-lifecycle.jsonl}"
PYTHON="${SSOT_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3
[ "$(uname -s)" = "Darwin" ] || exit 0
UID_N="$(id -u)"

log_event() {
  "$PYTHON" - "$LIFECYCLE_LOG" "$1" "$2" "$3" "$4" "${5:-0}" <<'PY' >/dev/null 2>&1 || true
import datetime, json, os, sys
path, event, active, last, pid, idle_s = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a', encoding='utf-8') as f:
    f.write(json.dumps({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                        'event': event, 'active': int(active or 0),
                        'last_query': int(last or 0), 'pid': int(pid or 0),
                        'idle_s': int(idle_s or 0),
                        'manual': int(os.environ.get('SSOT_SEMANTIC_REAP_MANUAL', '0') or 0)},
                       ensure_ascii=False) + '\n')
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

job_running() {
  launchctl print "gui/$UID_N/$LABEL" 2>/dev/null | grep -q '^\s*state = running'
}

read_state() {
  "$PYTHON" - "$STATE_PATH" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding='utf-8') as f:
        d = json.load(f)
    print(int(d.get('active', 0)), int(d.get('last_query', 0)),
          int(d.get('reloading', 0)), int(d.get('pid', 0)))
except Exception:
    sys.exit(1)
PY
}

if ! socket_ready; then
  if job_running; then
    log_event wait_start 0 0 0
    exit 0
  fi
  if [ -f "$LEASE" ]; then
    now="$(date +%s)"
    mtime="$(stat -f %m "$LEASE" 2>/dev/null || echo "$now")"
    age=$((now - mtime))
    if [ "$age" -ge "$LEASE_STALE" ]; then
      rm -f "$LEASE" "$STATE_PATH" "$SOCKET_PATH"
      log_event stale_cleanup 0 0 0 "$age"
    fi
  fi
  exit 0
fi

lease_present=1
[ -f "$LEASE" ] || lease_present=0

if ! state_line="$(read_state)"; then
  log_event state_invalid 0 0 0
  exit 0
fi
set -- $state_line
active="$1"; last_query="$2"; reloading="$3"; daemon_pid="$4"
if [ "$active" -gt 0 ] || [ "$reloading" -gt 0 ]; then
  log_event skip_active "$active" "$last_query" "$daemon_pid"
  exit 0
fi

now="$(date +%s)"
idle=$((now - last_query))
if [ "$lease_present" -eq 0 ]; then
  # 无租约 = 无消费者：stray daemon 至少超过 LEASE_STALE 才回收，避开启动窗口。
  if [ "$idle" -lt "$LEASE_STALE" ]; then
    exit 0
  fi
elif [ "$idle" -lt "$IDLE" ]; then
  exit 0
fi

idle_last_query="$last_query"
rm -f "$LEASE"
sleep 1
if ! state_line="$(read_state)"; then
  touch "$LEASE"
  log_event state_invalid 0 0 0
  exit 0
fi
set -- $state_line
active="$1"; last_query="$2"; reloading="$3"; daemon_pid="$4"
if [ "$active" -gt 0 ] || [ "$reloading" -gt 0 ] || [ "$last_query" -ne "$idle_last_query" ]; then
  touch "$LEASE"
  log_event skip_race "$active" "$last_query" "$daemon_pid"
  exit 0
fi
# acquire 可能在宽限期内 touch 了租约但还没发查询；kill 前再查一次。
if [ -f "$LEASE" ]; then
  log_event skip_race "$active" "$last_query" "$daemon_pid"
  exit 0
fi

log_event reap_start 0 "$last_query" "$daemon_pid" "$idle"
launchctl kill SIGTERM "gui/$UID_N/$LABEL" 2>/dev/null || true
# daemon 可能正在 drain 在途请求；给 15s，而不是 2s 就判失败。
i=0
term_ticks=$((TERM_WAIT * 2))
while [ "$i" -lt "$term_ticks" ] && socket_ready; do
  sleep 0.5
  i=$((i + 1))
done
if socket_ready; then
  touch "$LEASE"
  log_event term_failed 0 "$last_query" "$daemon_pid"
  exit 1
fi

rm -f "$STATE_PATH" "$SOCKET_PATH"
log_event reaped 0 "$last_query" "$daemon_pid" "$idle"
if [ "$LABEL" = "com.ssot.semantic" ] && [ "${SSOT_SEMANTIC_OBSERVE_ON_REAP:-1}" = "1" ] \
   && [ "${SSOT_SEMANTIC_REAP_MANUAL:-0}" != "1" ]; then
  observer="$SSOT_ROOT/tools/sp_semantic_observe.py"
  [ ! -f "$observer" ] || "$PYTHON" "$observer" --trigger reap >/dev/null 2>&1 || true
fi
exit 0

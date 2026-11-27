#!/usr/bin/env bash
set -euo pipefail

SSOT_ROOT="${SSOT_ROOT:-$HOME/ssot}"
LABEL="${SSOT_EG2_LABEL:-com.ssot.eg2}"
PORT="${SSOT_EG2_PORT:-8399}"
LEASE="${SSOT_EG2_LEASE:-/tmp/ssot-eg2.want}"
IDLE="${SSOT_EG2_IDLE_SEC:-1800}"
TERM_WAIT="${SSOT_EG2_TERM_WAIT_SEC:-5}"
# 服务未运行时清理残留租约的年龄阈值。必须留出 acquire touch → launchd 拉起
# 的窗口；否则 reaper 可能在冷启动竞态里删掉刚 touch 的租约，导致 acquire 超时。
LEASE_STALE="${SSOT_EG2_LEASE_STALE_SEC:-120}"
LIFECYCLE_LOG="${SSOT_EG2_LIFECYCLE_LOG:-$SSOT_ROOT/logs/eg2-lifecycle.jsonl}"
PYTHON="${SSOT_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$PYTHON" ] || PYTHON=/usr/bin/python3
[ "$(uname -s)" = "Darwin" ] || exit 0
UID_N="$(id -u)"

log_event() {
  "$PYTHON" - "$LIFECYCLE_LOG" "$1" "$2" <<'PY' >/dev/null 2>&1 || true
import datetime, json, os, sys
path, event, idle = sys.argv[1:]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'a', encoding='utf-8') as f:
    f.write(json.dumps({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                        'event': event, 'idle_s': int(idle or 0), 'pid': os.getpid()},
                       ensure_ascii=False) + '\n')
PY
}

health() { curl -fsS -m 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; }
has_active() { lsof -nP -iTCP:"${PORT}" -sTCP:ESTABLISHED 2>/dev/null | tail -n +2 | grep -q .; }
job_running() { launchctl print "gui/$UID_N/$LABEL" 2>/dev/null | grep -q '^\s*state = running'; }

if ! health; then
  if job_running; then
    log_event wait_start 0
    exit 0
  fi
  if [ -f "$LEASE" ]; then
    now="$(date +%s)"
    mtime="$(stat -f %m "$LEASE" 2>/dev/null || echo "$now")"
    age=$((now - mtime))
    if [ "$age" -ge "$LEASE_STALE" ]; then
      rm -f "$LEASE"
      log_event stale_cleanup "$age"
    fi
  fi
  exit 0
fi

# 活跃连接是硬保护：顺手刷新租约，避免长连接期间租约过期。
if has_active; then
  touch "$LEASE"
  exit 0
fi

now="$(date +%s)"
idle=0
if [ -f "$LEASE" ]; then
  mtime="$(stat -f %m "$LEASE" 2>/dev/null || echo "$now")"
  idle=$((now - mtime))
  if [ "$idle" -lt "$IDLE" ]; then
    exit 0
  fi
fi
# 租约不存在 = 已无任何消费者；PathState 不会因此停服务（A589），必须显式回收。

rm -f "$LEASE"
sleep 1
health || { log_event reaped "$idle"; exit 0; }
if [ -f "$LEASE" ]; then exit 0; fi
# 宽限期内新建立的 ESTABLISHED 是硬保护；kill 前必须再查一次。
if has_active; then
  touch "$LEASE"
  log_event skip_race "$idle"
  exit 0
fi

log_event reap_start "$idle"
launchctl kill SIGTERM "gui/$UID_N/$LABEL" 2>/dev/null || true
i=0
term_ticks=$((TERM_WAIT * 2))
while [ "$i" -lt "$term_ticks" ] && health; do
  sleep 0.5
  i=$((i + 1))
done
if health; then
  touch "$LEASE"
  log_event term_failed "$idle"
  exit 1
fi

log_event reaped "$idle"
exit 0

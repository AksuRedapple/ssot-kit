#!/usr/bin/env bash
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --root) ROOT="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "❌ install-semantic 当前仅支持 macOS；Linux 保持 sp_semantic 一次性路径"
  exit 1
fi

PYTHON="${SSOT_PYTHON:-/opt/homebrew/bin/python3}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
for f in sp_semantic_daemon.py sp_semantic_acquire.sh sp_semantic_reaper.sh; do
  [ -f "$ROOT/tools/$f" ] || { echo "❌ 缺 $ROOT/tools/$f"; exit 1; }
done

"$PYTHON" - "$ROOT" "$PYTHON" "$DRY" <<'PY'
import os, plistlib, sys
root, python, dry = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
home = os.path.expanduser('~')
lease = '/tmp/ssot-semantic.want'
state = '/tmp/ssot-semantic.state.json'
sock = os.path.join(home, '.ssot', 'semantic.sock')
logdir = os.path.join(home, 'Library', 'Logs', 'ssot')
os.makedirs(logdir, exist_ok=True)
sem = {
    'Label': 'com.ssot.semantic',
    'ProgramArguments': [python, os.path.join(root, 'tools/sp_semantic_daemon.py')],
    'WorkingDirectory': root,
    'KeepAlive': {'PathState': {lease: True}},
    'ThrottleInterval': 10,
    'EnvironmentVariables': {'SSOT_ROOT': root, 'SSOT_SEMANTIC_SOCKET': sock,
                             'SSOT_SEMANTIC_STATE': state},
    'StandardOutPath': os.path.join(logdir, 'semantic.out'),
    'StandardErrorPath': os.path.join(logdir, 'semantic.err'),
}
rep = {
    'Label': 'com.ssot.semantic-reaper',
    'ProgramArguments': ['/bin/bash', os.path.join(root, 'tools/sp_semantic_reaper.sh')],
    'RunAtLoad': False, 'StartInterval': 120,
    'EnvironmentVariables': {'SSOT_ROOT': root, 'SSOT_SEMANTIC_LABEL': 'com.ssot.semantic',
                             'SSOT_SEMANTIC_LEASE': lease, 'SSOT_SEMANTIC_STATE': state,
                             'SSOT_SEMANTIC_SOCKET': sock},
    'StandardOutPath': os.path.join(logdir, 'semantic-reaper.log'),
    'StandardErrorPath': os.path.join(logdir, 'semantic-reaper.log'),
}
for name, data in (('com.ssot.semantic', sem), ('com.ssot.semantic-reaper', rep)):
    path = os.path.join(home, 'Library', 'LaunchAgents', name + '.plist')
    if dry:
        print(path)
        print(plistlib.dumps(data).decode())
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            plistlib.dump(data, f)
PY

if [ "$DRY" = "1" ]; then exit 0; fi
uid="$(id -u)"
launchctl bootout "gui/$uid/com.ssot.semantic" 2>/dev/null || true
launchctl bootout "gui/$uid/com.ssot.semantic-reaper" 2>/dev/null || true
sleep 2
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.ssot.semantic.plist"
launchctl bootstrap "gui/$uid" "$HOME/Library/LaunchAgents/com.ssot.semantic-reaper.plist"
echo "✅ semantic 按需服务已加载（首次查询自动唤醒，空闲 30 分钟回收）"

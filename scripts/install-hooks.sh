#!/usr/bin/env bash
# ssot-kit · 安装/卸载 hooks（SessionStart / UserPromptSubmit / Stop）
# 用法: bash scripts/install-hooks.sh [--dry] [--uninstall] [--root DIR] [--settings PATH]
# 默认 settings = ~/.qoder/settings.json；Claude 用 --settings ~/.claude/settings.json
# 行为：幂等合并，保留已有 hooks；写入前自动备份；--dry 不落盘、不打印既有配置内容。
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
SETTINGS="${HOME}/.qoder/settings.json"
DRY=0
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --root) ROOT="$2"; shift 2 ;;
    --settings) SETTINGS="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done
KIT="$(cd "$(dirname "$0")/.." && pwd)"
SETTINGS="${SETTINGS/#\~/$HOME}"
ROOT="${ROOT/#\~/$HOME}"

if [ "$UNINSTALL" = "0" ] && [ "$DRY" = "0" ]; then
  mkdir -p "$ROOT/tools/hooks"
  cp -f "$KIT/hooks/"*.sh "$ROOT/tools/hooks/"
  chmod +x "$ROOT/tools/hooks/"*.sh
  echo "── hooks 已同步 → $ROOT/tools/hooks/"
elif [ "$DRY" = "1" ]; then
  echo "── （dry）不复制 hooks、不写 settings"
fi

python3 - "$SETTINGS" "$ROOT" "$DRY" "$UNINSTALL" <<'PY'
import datetime
import json
import os
import shlex
import shutil
import sys

settings, root, dry, uninstall = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4] == "1"
hooks_dir = os.path.join(root, "tools", "hooks")
spec = [("SessionStart", "session-start.sh", 30),
        ("UserPromptSubmit", "user-prompt-retrieval.sh", 30),
        ("Stop", "stop-draft.sh", 10)]

if uninstall and not os.path.exists(settings):
    print("（无 settings，跳过）")
    sys.exit(0)

data = {}
if os.path.exists(settings):
    try:
        with open(settings, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        sys.exit(f"❌ settings JSON 解析失败（未改动）：{e}")
if not isinstance(data, dict):
    sys.exit("❌ settings 顶层不是对象（未改动）")

hooks = data.get("hooks") or {}
if not isinstance(hooks, dict):
    sys.exit("❌ settings.hooks 不是对象（未改动）")

def command_for(script):
    return f"bash {shlex.quote(os.path.join(hooks_dir, script))}"

def is_ours(cmd):
    return "ssot-kit-hooks" in cmd or hooks_dir in cmd

if uninstall:
    for event in list(hooks):
        groups = hooks[event]
        kept_groups = []
        for g in groups:
            kept = [h for h in g.get("hooks", []) if not is_ours(h.get("command", ""))]
            if kept:
                g2 = dict(g)
                g2["hooks"] = kept
                kept_groups.append(g2)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            hooks.pop(event, None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    print("（dry）将移除 ssot-kit hooks" if dry else "✅ 已移除 ssot-kit hooks")
else:
    for event, script, timeout in spec:
        groups = hooks.setdefault(event, [])
        present = any(is_ours(h.get("command", "")) for g in groups for h in g.get("hooks", []))
        if present:
            print(f"  已存在: {event}")
            continue
        groups.append({"hooks": [{"type": "command", "command": command_for(script),
                                  "timeout": timeout}]})
        print(f"  + {event}: {command_for(script)}")
    data["hooks"] = hooks
    print("（dry）未写入" if dry else f"✅ hooks 已写入 {settings}")

if dry:
    sys.exit(0)

os.makedirs(os.path.dirname(settings) or ".", exist_ok=True)
if os.path.exists(settings):
    bak = settings + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(settings, bak)
    print(f"  备份: {bak}")
tmp = settings + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
os.replace(tmp, settings)
PY

echo "提示：Qoder 用默认 settings；Claude 追加 --settings ~/.claude/settings.json"

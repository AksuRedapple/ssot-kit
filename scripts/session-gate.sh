#!/usr/bin/env bash
# ssot-kit · 发布/交接门禁：确认当前会话在 registry 有行。
# 用法: bash scripts/session-gate.sh [publish|handoff] [--sid SID] [--root DIR]
# 退出码：0=有行；1=无行；2=无法验证（缺 sid/registry）
set -u

ROOT="${SSOT_ROOT:-$HOME/ssot}"
MODE="publish"
SID="${QODER_SESSION_ID:-${CLAUDE_SESSION_ID:-}}"
while [ $# -gt 0 ]; do
  case "$1" in
    publish|handoff) MODE="$1"; shift ;;
    --sid) SID="$2"; shift 2 ;;
    --root) ROOT="$2"; shift 2 ;;
    -h|--help) echo "用法: bash scripts/session-gate.sh [publish|handoff] [--sid SID] [--root DIR]"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

REG="$ROOT/sessions/registry.md"
if [ ! -f "$REG" ]; then
  echo "⚠️ 无法验证（$MODE）：缺 $REG" >&2
  exit 2
fi
if [ -z "$SID" ]; then
  echo "⚠️ 无法验证（$MODE）：未提供 session id（--sid 或设置 QODER_SESSION_ID）" >&2
  exit 2
fi
SID8=$(printf '%s' "$SID" | tr -cd 'A-Za-z0-9-' | cut -c1-8)
if [ -z "$SID8" ]; then
  echo "⚠️ 无法验证（$MODE）：session id 非法" >&2
  exit 2
fi

if grep -q "$SID8" "$REG"; then
  echo "✅ 门禁通过（$MODE）：$SID8 在 registry.md"
  exit 0
fi
echo "❌ 门禁拒绝（$MODE）：$SID8 无 registry 行" >&2
echo "   先在 $REG 追加一行（日期/线/主题/状态/干到哪了/指针），再发布或交接。" >&2
exit 1

#!/usr/bin/env bash
mkdir -p "${ROOT:-$HOME/ssot}/alerts" 2>/dev/null || true
# ssot-kit · SessionStart hook：只注入指针与现场态，不推送长文。
# 安装：bash scripts/install-hooks.sh（写入 ~/.qoder/settings.json 或 --settings 指定文件）
set -u

ROOT="${SSOT_ROOT:-$HOME/ssot}"

if [ -f "$ROOT/START.md" ]; then
  echo "[SSOT] 全局记忆中枢 → $ROOT/START.md ｜ 线索 lines/ ｜ 贡献写 inbox/（fact 必带 source、decision 必带 owner）"
fi

if [ -f "$ROOT/tools/sp_semantic.py" ]; then
  echo "[记忆检索] 按意思搜全库：python3 $ROOT/tools/sp_semantic.py \"<问题>\" --expand --top 5 ｜ 回忆/接手/取证先查再答"
elif [ -f "$ROOT/tools/kb_search.py" ]; then
  echo "[记忆检索] 按意思搜本机库：python3 $ROOT/tools/kb_search.py \"<问题>\" --root \"$ROOT\" --top 5（服务 8399）｜ 回忆/接手/取证先查再答"
fi

if [ -f "./.memory/context.md" ]; then
  echo
  echo "## 项目现场记忆（.memory · 本段由 SessionStart 自动注入）"
  echo "### context.md（前 60 行）"
  head -n 60 ./.memory/context.md
  if [ -f "./.memory/handoff/latest.md" ]; then
    echo
    echo "### handoff/latest.md（前 40 行）"
    head -n 40 ./.memory/handoff/latest.md
  fi
  if [ -f "./.memory/session-buffer.md" ]; then
    echo
    echo "### session-buffer.md（尾 15 行）"
    tail -n 15 ./.memory/session-buffer.md
  fi
fi

exit 0

#!/usr/bin/env bash
mkdir -p "${ROOT:-$HOME/ssot}/alerts" 2>/dev/null || true
# ssot-kit · UserPromptSubmit hook：命中「回忆句式」才查，top-3 注入，不每轮全查。
# 关停：touch $ROOT/.retrieval-off（或 SSOT_RETRIEVAL_OFF=1）
set -u

ROOT="${SSOT_ROOT:-$HOME/ssot}"
[ -f "$ROOT/.retrieval-off" ] && exit 0
[ "${SSOT_RETRIEVAL_OFF:-0}" = "1" ] && exit 0

IN=$(cat)
PROMPT=$(printf '%s' "$IN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt') or d.get('user_prompt') or '')
except Exception:
    sys.stdout.write('')" 2>>"$ROOT/alerts/hook.err")
[ -z "$PROMPT" ] && exit 0

# 保守触发词：只认明确的回忆/取证句式，防日常词误触。
# 单一真源：$ROOT/tools/recall-phrases.json（缺失时用内嵌 fallback）。
RX="还记得|记得吗|以前(说|提|做|那个|我们|的)|上次(说|提|做|讨论|那个|的)|之前(说|提|做|讨论|那个|提到|的)|早先|前面说过|回顾一下|找一找.*(之前|以前|历史|那个)|(之前|以前)的(会话|记录|讨论)|那时候我们|当时我们|历史(会话|记录|里)"
PHRASES="$ROOT/tools/recall-phrases.json"
if [ -f "$PHRASES" ]; then
  LOADED=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("regex",""))' "$PHRASES" 2>>"$ROOT/alerts/hook.err")
  [ -n "$LOADED" ] && RX="$LOADED"
fi
printf '%s' "$PROMPT" | grep -qE "$RX" || exit 0

SID=$(printf '%s' "$IN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('session_id') or d.get('sessionId') or '-')
except Exception:
    print('-')" 2>>"$ROOT/alerts/hook.err")
Q=$(printf '%s' "$PROMPT" | tr '\n' ' ' | head -c 200)
HEALTH="http://127.0.0.1:8399/health"

# 8399 不在时按需拉起（SSOT_EMBED_AUTOSTART=0 可关；steward 只探测、不拉起，二者不抢）
ensure_embed() {
  curl -s -m 2 "$HEALTH" >/dev/null 2>&1 && return 0
  [ "${SSOT_EMBED_AUTOSTART:-1}" = "0" ] && return 1
  local model="${EMBED_MODEL:-$ROOT/models/embeddinggemma-2-BF16.gguf}"
  [ -f "$model" ] || return 1
  [ -f "$ROOT/tools/serve_embed.sh" ] || return 1
  local lock="$ROOT/.embed-start.lock"
  if mkdir "$lock" 2>>"$ROOT/alerts/hook.err"; then
    (cd "$ROOT" && nohup bash tools/serve_embed.sh >/tmp/ssot-embed.log 2>&1 &) || true
    for _ in 1 2 3 4 5; do
      sleep 1
      curl -s -m 1 "$HEALTH" >/dev/null 2>&1 && { rmdir "$lock" 2>>"$ROOT/alerts/hook.err" || true; return 0; }
    done
    rmdir "$lock" 2>>"$ROOT/alerts/hook.err" || true
    return 1
  fi
  for _ in 1 2 3 4 5; do
    sleep 1
    curl -s -m 1 "$HEALTH" >/dev/null 2>&1 && return 0
  done
  return 1
}

OUT=""
if [ -f "$ROOT/tools/sp_semantic.py" ] && ensure_embed; then
  OUT=$(cd "$ROOT" && SSOT_CALLER=hook SSOT_SESSION_ID="${SID:--}" \
    python3 tools/sp_semantic.py "$Q" --expand --top 3 2>/tmp/ssot-semantic.err | tail -n +3 | head -n 12)
  if [ -z "$OUT" ]; then
    echo "[ssot] 语义检索不可用（已降级；原因见 /tmp/ssot-semantic.err）" >&2
  fi
elif [ -f "$ROOT/tools/kb_search.py" ] && [ -f "$ROOT/kb-index/kb.db" ] \
     && curl -s -m 2 http://127.0.0.1:8399/health >/dev/null 2>&1; then
  OUT=$(cd "$ROOT" && SSOT_CALLER=hook SSOT_SESSION_ID="${SID:--}" \
    python3 tools/kb_search.py "$Q" --root "$ROOT" --top 3 2>>"$ROOT/alerts/hook.err" | head -n 12)
fi
[ -z "$OUT" ] && exit 0

echo "【记忆检索·自动触发】命中回忆句式，已查本地库 top-3（参考用，可忽略）："
echo "$OUT"
echo "--（出处见 path:line；要深查再跑一次检索命令）"
exit 0

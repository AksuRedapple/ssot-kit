#!/usr/bin/env bash
# 本地嵌入服务（llama.cpp，OpenAI 兼容 /v1/embeddings）
# 前置：llama-server 已装、模型已放 $ROOT/models/embeddinggemma-2-BF16.gguf（见 docs/SEMANTIC.md）
# 用法：nohup bash ~/ssot/tools/serve_embed.sh > /tmp/embed.log 2>&1 &
#
# 配置优先级：环境变量 EMBED_C/B/UB/PARALLEL > profile/embed-profile.json > 默认值。
# 只读检查：EMBED_CONFIG_DRY=1 bash tools/serve_embed.sh   # 打印最终命令，不启动
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
PORT="${EMBED_PORT:-8399}"
MODEL="${EMBED_MODEL:-}"
LLAMA="${LLAMA_SERVER:-llama-server}"
PROFILE="${EMBED_PROFILE:-$ROOT/profile/embed-profile.json}"

P_C=""; P_B=""; P_UB=""; P_PAR=""; P_MODEL=""
if [ -f "$PROFILE" ]; then
  eval "$(python3 - "$PROFILE" <<'PY'
import json, shlex, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    d = {}
for k, env in (('c', 'C'), ('b', 'B'), ('ub', 'UB'), ('parallel', 'PAR')):
    v = (d.get('server') or {}).get(k)
    if isinstance(v, int) and v > 0:
        print('P_%s=%d' % (env, v))
m = d.get('model_path') or (d.get('model') or {}).get('path')
if isinstance(m, str) and m:
    print('P_MODEL=' + shlex.quote(m))
PY
)" 2>/dev/null || true
fi
MODEL="${MODEL:-${P_MODEL:-$ROOT/models/embeddinggemma-2-BF16.gguf}}"

C="${EMBED_C:-${P_C:-8192}}"
B="${EMBED_B:-${P_B:-2048}}"
UB="${EMBED_UB:-${P_UB:-2048}}"
PAR="${EMBED_PARALLEL:-${P_PAR:-4}}"

is_int() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }
for v in C B UB PAR; do
  eval "val=\${$v}"
  is_int "$val" || { echo "⚠️ 非法 $v=$val，回退默认值"; case "$v" in C) C=8192;; B) B=2048;; UB) UB=2048;; PAR) PAR=4;; esac; }
done

# 硬约束：ub <= b；每个 slot 至少 512 上下文；总上下文 = parallel * slot_ctx
[ "$UB" -gt "$B" ] && UB="$B"
[ "$B" -lt 64 ] && B=64
[ "$UB" -lt 64 ] && UB=64
[ "$PAR" -lt 1 ] && PAR=1
MIN_CTX=$((PAR * 512))
if [ "$C" -lt "$MIN_CTX" ]; then
  echo "⚠️ c=$C 小于 parallel*512=$MIN_CTX，已抬到下限（否则 slot 会被截断）"
  C="$MIN_CTX"
fi

echo "配置: c=$C b=$B ub=$UB parallel=$PAR  (profile=${PROFILE}${P_C:+ · 已读})"

if [ "${EMBED_CONFIG_DRY:-0}" = "1" ]; then
  printf '%s\n' "$LLAMA --model $MODEL --embeddings --pooling mean -c $C -b $B -ub $UB --parallel $PAR --host 127.0.0.1 --port $PORT --no-ui"
  exit 0
fi

if [ ! -f "$MODEL" ]; then
  echo "❌ 缺模型: $MODEL"; echo "   拉取方法见 docs/SEMANTIC.md（权重不入库，按需自拉）"; exit 1
fi
if ! command -v "$LLAMA" >/dev/null 2>&1; then
  echo "❌ 找不到 llama-server（$LLAMA）——安装方法见 docs/SEMANTIC.md"; exit 1
fi

echo "启动嵌入服务: $LLAMA  model=$MODEL  port=$PORT"
exec "$LLAMA" --model "$MODEL" --embeddings --pooling mean \
  -c "$C" -b "$B" -ub "$UB" --parallel "$PAR" \
  --host 127.0.0.1 --port "$PORT" --no-ui

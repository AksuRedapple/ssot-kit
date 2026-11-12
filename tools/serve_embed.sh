#!/usr/bin/env bash
# 本地嵌入服务（llama.cpp，OpenAI 兼容 /v1/embeddings）
# 前置：llama-server 已装、模型已放 $ROOT/models/embeddinggemma-2-BF16.gguf（见 docs/SEMANTIC.md）
# 用法：nohup bash scripts/semantic/serve_embed.sh > /tmp/embed.log 2>&1 &
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
PORT="${EMBED_PORT:-8399}"
MODEL="${EMBED_MODEL:-$ROOT/models/embeddinggemma-2-BF16.gguf}"
LLAMA="${LLAMA_SERVER:-llama-server}"

if [ ! -f "$MODEL" ]; then
  echo "❌ 缺模型: $MODEL"; echo "   拉取方法见 docs/SEMANTIC.md（权重不入库，按需自拉）"; exit 1
fi
if ! command -v "$LLAMA" >/dev/null 2>&1; then
  echo "❌ 找不到 llama-server（$LLAMA）——安装方法见 docs/SEMANTIC.md"; exit 1
fi

echo "启动嵌入服务: $LLAMA  model=$MODEL  port=$PORT"
exec "$LLAMA" --model "$MODEL" --embeddings --pooling mean \
  -c 8192 -b 2048 -ub 2048 --parallel 4 \
  --host 127.0.0.1 --port "$PORT" --no-ui

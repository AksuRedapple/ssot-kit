#!/usr/bin/env bash
# 回归：serve_embed.sh 读 profile / env / 硬约束；EMBED_CONFIG_DRY 不启动（2026-11-18）
set -u
SSOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

mkdir -p "$T/profile" "$T/models"
: > "$T/models/embeddinggemma-2-BF16.gguf"
PROFILE="$T/profile/embed-profile.json"

# 1) profile 生效
printf '{"server":{"c":4096,"b":1024,"ub":512,"parallel":2}}\n' > "$PROFILE"
out=$(SSOT_ROOT="$T" EMBED_CONFIG_DRY=1 bash "$SSOT_DIR/tools/serve_embed.sh" 2>&1)
chk "$(printf '%s' "$out" | grep -c -- '-c 4096 -b 1024 -ub 512 --parallel 2')" "1" "profile 数值被采用"

# 2) 环境变量覆盖 + c 下限（parallel*512）
out=$(SSOT_ROOT="$T" EMBED_CONFIG_DRY=1 EMBED_C=2048 EMBED_PARALLEL=8 bash "$SSOT_DIR/tools/serve_embed.sh" 2>&1)
chk "$(printf '%s' "$out" | grep -c -- '-c 4096 -b 1024 -ub 512 --parallel 8')" "1" "env 覆盖并抬到 c 下限"

# 3) ub > b 被夹紧
printf '{"server":{"c":8192,"b":1024,"ub":2048,"parallel":2}}\n' > "$PROFILE"
out=$(SSOT_ROOT="$T" EMBED_CONFIG_DRY=1 bash "$SSOT_DIR/tools/serve_embed.sh" 2>&1)
chk "$(printf '%s' "$out" | grep -c -- '-b 1024 -ub 1024')" "1" "ub 不超过 b"

# 4) 坏 profile 回退默认
printf '{bad json\n' > "$PROFILE"
out=$(SSOT_ROOT="$T" EMBED_CONFIG_DRY=1 bash "$SSOT_DIR/tools/serve_embed.sh" 2>&1)
chk "$(printf '%s' "$out" | grep -c -- '-c 8192 -b 2048 -ub 2048 --parallel 4')" "1" "坏 profile 回退默认"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

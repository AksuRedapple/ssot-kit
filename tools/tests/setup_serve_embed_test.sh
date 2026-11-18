#!/usr/bin/env bash
# 回归：setup 必须把 serve_embed.sh 落到 $ROOT/tools（install-service 依赖）2026-11-18
set -u
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

bash "$KIT/tools/install/setup.sh" --root "$T/ssot" --skills-dir "$T/skills" >/tmp/setup-embed.out 2>&1
chk "$?" "0" "setup rc=0"
chk "$([ -f "$T/ssot/tools/serve_embed.sh" ] && echo y || echo n)" "y" "serve_embed.sh 已落位"
chk "$([ -x "$T/ssot/tools/serve_embed.sh" ] && echo y || echo n)" "y" "serve_embed.sh 可执行"
chk "$([ -f "$T/ssot/.gitignore" ] && echo y || echo n)" "y" "实例 .gitignore 已落位"
chk "$([ -f "$T/ssot/profile/index-policy.json" ] && echo y || echo n)" "y" "index-policy 模板已落位"
chk "$([ -f "$T/ssot/profile/golden-queries.jsonl" ] && echo y || echo n)" "y" "golden 模板已落位"

# update 也应同步（用同一套复制逻辑，--skip-pull 不联网）
bash "$KIT/tools/install/update.sh" --root "$T/ssot" --skip-pull --dry >/tmp/update-embed.out 2>&1
chk "$?" "0" "update --dry rc=0"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

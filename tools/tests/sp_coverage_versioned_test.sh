#!/usr/bin/env bash
# 回归：sp_coverage 必须读 active 版本库（2026-11-18）
# 事故形态：--adopt/--full 后根 index.db 已移入 versions/，coverage 仍读旧路径 → 已索引恒为 0。
set -u
SSOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

# 假实例：一个 qoder 会话，S0/S1 各一份，索引放在版本目录
mkdir -p "$T/evidence/qoder/S0-archive/qoder-projects/proj" \
         "$T/evidence/qoder/S1-sessions/2026-01-01-abcdef12-t" \
         "$T/S2-index/semantic/versions/v1" "$T/profile"
printf '{"type":"user"}\n' > "$T/evidence/qoder/S0-archive/qoder-projects/proj/abcdef12-0000-0000-0000-000000000000.jsonl"
python3 - "$T" <<'PY'
import sys, os
t = sys.argv[1]
p = os.path.join(t, 'evidence/qoder/S1-sessions/2026-01-01-abcdef12-t/transcript.jsonl')
open(p, 'w').write('{"role":"user","content":"x"}\n' * 200)
PY
printf '{"version":"v1"}\n' > "$T/S2-index/semantic/active.json"
printf '{"qoder":{"role":"human","extract":true}}\n' > "$T/profile/sources.json"
python3 - "$T" <<'PY'
import sqlite3, sys, os
p = os.path.join(sys.argv[1], 'S2-index/semantic/versions/v1/index.db')
con = sqlite3.connect(p)
con.execute('create table chunks(path text, text text)')
con.execute("insert into chunks values ('evidence/qoder/S1-sessions/2026-01-01-abcdef12-t/transcript.jsonl','x')")
con.commit(); con.close()
PY

out=$(SSOT_ROOT="$T" python3 "$SSOT_DIR/tools/sp_coverage.py" --json 2>&1)
chk "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["db"].endswith("versions/v1/index.db"))')" "True" "db 指向 active 版本库"
chk "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sources"][0]["covered"])')" "1" "版本库里的会话被计入已索引"
chk "$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sources"][0]["status"])')" "ok" "状态为 ok"

# legacy 回退：没有 active.json 时仍读根 index.db
rm -f "$T/S2-index/semantic/active.json"
cp "$T/S2-index/semantic/versions/v1/index.db" "$T/S2-index/semantic/index.db"
out2=$(SSOT_ROOT="$T" python3 "$SSOT_DIR/tools/sp_coverage.py" --json 2>&1)
chk "$(printf '%s' "$out2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["db"].endswith("semantic/index.db"))')" "True" "legacy 根库回退"
chk "$(printf '%s' "$out2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sources"][0]["covered"])')" "1" "legacy 根库会话可读"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

#!/bin/bash
# sp_index 摘要口径回归（2026-11-04 · A531）
#   ① meta 的 schema 等非进块字段不改变摘要（m0002 整库盖章不得触发重嵌）
#   ② title/start 等进块字段变了摘要必须变
#   ③ --restamp 只迁口径：旧口径摘要 → 新口径；内容真变过的源不吞
set -u
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
V="$T/ssot"; TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }
chkn(){ [ "$1" != "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（不应相等）"; fail=1; }; }
export HOME="$T" SSOT_ROOT="$V"

mkdir -p "$V/profile" "$V/evidence/qoder/S1-sessions/s1" "$V/S2-index/semantic"
printf '{"contract":2,"since":"2026-11-04"}' > "$V/profile/contract.json"
META="$V/evidence/qoder/S1-sessions/s1/meta.json"
JL="$V/evidence/qoder/S1-sessions/s1/transcript.jsonl"
printf '{"title":"会话甲","start":"2026-11-04T09:00:00","schema":2}' > "$META"
printf '%s\n' '{"kind":"text","role":"user","content":"帮我修一下索引摘要口径的问题","t":"2026-11-04T09:01:00"}' > "$JL"

digest(){ python3 - "$TOOLS" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import sp_index
print(sp_index.s1_groups()[0][1])
PY
}
legacy(){ python3 - "$TOOLS" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import sp_index
jl = sp_index.SSOT + '/evidence/qoder/S1-sessions/s1/transcript.jsonl'
mj = sp_index.SSOT + '/evidence/qoder/S1-sessions/s1/meta.json'
print(sp_index.S1VER + ':' + sp_index.md5_files(jl, mj))
PY
}

echo "[1] 非进块字段不进指纹"
d0=$(digest)
printf '{"title":"会话甲","start":"2026-11-04T09:00:00","schema":3}' > "$META"
chk "$(digest)" "$d0" "meta.schema 2→3 摘要不变"
printf '{"title":"会话乙","start":"2026-11-04T09:00:00","schema":3}' > "$META"
chkn "$(digest)" "$d0" "title 变 → 摘要变"
printf '{"title":"会话甲","start":"2026-11-04T09:00:00","schema":3}' > "$META"
chk "$(digest)" "$d0" "title 改回 → 摘要复原"

echo "[2] restamp：旧口径摘要迁到新口径"
python3 - "$V" "$(legacy)" <<'PY'
import sqlite3, sys
db = sys.argv[1] + '/S2-index/semantic/index.db'
con = sqlite3.connect(db)
con.execute('create table chunks(id integer primary key, path text, line integer, '
            'text text, role text, ts text, vec blob)')
con.execute('create table src_state(path text primary key, digest text)')
con.execute('insert into src_state values(?,?)',
            ('evidence/qoder/S1-sessions/s1/transcript.jsonl', sys.argv[2]))
con.commit(); con.close()
PY
python3 "$TOOLS/sp_index.py" --restamp >/dev/null 2>&1; rc=$?
chk "$rc" "0" "restamp rc=0"
got=$(sqlite3 "$V/S2-index/semantic/index.db" \
  "select digest from src_state where path='evidence/qoder/S1-sessions/s1/transcript.jsonl'")
chk "$got" "$(digest)" "src_state 已换新口径"
chk "$(sqlite3 "$V/S2-index/semantic/index.db" 'select count(*) from chunks')" "0" "restamp 不写块"
chk "$(python3 -c "import json;print(json.load(open('$V/S2-index/semantic/BUILD.json')).get('schema'))")" "2" "BUILD 盖 schema:2"

echo "[3] restamp 不吞内容变化"
printf '%s\n' '{"kind":"text","role":"assistant","content":"好的，我来看摘要口径","t":"2026-11-04T09:02:00"}' >> "$JL"
before=$(sqlite3 "$V/S2-index/semantic/index.db" \
  "select digest from src_state where path='evidence/qoder/S1-sessions/s1/transcript.jsonl'")
out=$(python3 "$TOOLS/sp_index.py" --restamp 2>&1)
after=$(sqlite3 "$V/S2-index/semantic/index.db" \
  "select digest from src_state where path='evidence/qoder/S1-sessions/s1/transcript.jsonl'")
chk "$after" "$before" "内容变过的源不改写"
printf '%s' "$out" | grep -q '内容有变' && echo "  ok   报告提示内容有变" || { echo "  FAIL 报告缺提示"; fail=1; }

[ "$fail" -eq 0 ] && { echo "全部通过"; exit 0; } || { echo "有失败"; exit 1; }

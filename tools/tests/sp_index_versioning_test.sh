#!/bin/bash
# sp_index 版本化发布回归（2026-11-12 · 0.12.0）
#   ① --adopt 把 legacy 单库收编成版本并切 active
#   ② --activate 原子切指针，旧版标 retired
#   ③ --rollback 指回上一版
#   ④ --status 只读输出 active（构建中也能跑）
set -u
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
V="$T/ssot"; TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

export HOME="$T"
mkdir -p "$V/profile" "$V/S2-index/semantic"
printf '{"contract":2,"since":"2026-11-12"}' > "$V/profile/contract.json"

# 假 legacy 库：2 块
python3 - "$V/S2-index/semantic/index.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute('create table chunks(id integer primary key, path text, line integer, text text, role text, ts text, vec blob)')
c.executemany('insert into chunks(path,line,text,role,ts,vec) values(?,?,?,?,?,?)',
              [('a.md',1,'第一块','user','',b'x'), ('a.md',2,'第二块','user','',b'y')])
c.commit()
PY
printf '{"chunks":2}' > "$V/S2-index/semantic/BUILD.json"

idx="python3 $TOOLS/sp_index.py"

echo "[1] --adopt"
$idx --adopt >/dev/null 2>&1
act=$(python3 -c "import json;print(json.load(open('$V/S2-index/semantic/active.json'))['version'])" 2>/dev/null)
[ -n "$act" ] && echo "  ok   active=$act" || { echo "  FAIL 没有 active.json"; fail=1; }
n=$(python3 -c "import sqlite3;print(sqlite3.connect('$V/S2-index/semantic/versions/$act/index.db').execute('select count(*) from chunks').fetchone()[0])" 2>/dev/null)
chk "${n:-0}" "2" "版本库保留 2 块"

echo "[2] 造第二版 + --activate"
cp -R "$V/S2-index/semantic/versions/$act" "$V/S2-index/semantic/versions/v2test"
printf 'ready\n' > "$V/S2-index/semantic/versions/v2test/STATUS"
$idx --activate v2test >/dev/null 2>&1
act2=$(python3 -c "import json;print(json.load(open('$V/S2-index/semantic/active.json'))['version'])")
chk "$act2" "v2test" "active 切到 v2test"
st=$(cat "$V/S2-index/semantic/versions/$act/STATUS" 2>/dev/null | tr -d '\n')
chk "$st" "retired" "旧版标 retired"

echo "[3] --rollback"
$idx --rollback >/dev/null 2>&1
act3=$(python3 -c "import json;print(json.load(open('$V/S2-index/semantic/active.json'))['version'])")
chk "$act3" "$act" "回滚到上一版"

echo "[4] --status"
out=$($idx --status 2>&1)
echo "$out" | grep -q "active: $act" && echo "  ok   status 报 active" || { echo "  FAIL status 输出：$out"; fail=1; }

[ "$fail" = 0 ] && echo "✅ 版本化回归全过" || echo "❌ 有失败"
exit "$fail"

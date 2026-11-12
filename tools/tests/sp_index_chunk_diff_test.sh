#!/bin/bash
# 块级 diff 验收(2026-11-06):同 (text,role,ts) 复用旧向量，不调用嵌入服务
set -u
export KIT="$(cd "$(dirname "$0")/../.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3(期望 $2,得 $1)"; fail=1; }; }

out=$(python3 - "$T/db.sqlite" <<'PY'
import sqlite3, sys, struct, os
sys.path.insert(0, os.path.join(os.environ['KIT'], 'tools'))
import sp_index
con=sqlite3.connect(sys.argv[1])
con.execute('create table chunks(id integer primary key,path text,line integer,text text,role text,ts text,vec blob)')
old_rows={'a.md': [(1,'same','','',struct.pack('<4f',1,0,0,0)),
                   (2,'same','','',struct.pack('<4f',0,1,0,0))]}
blocks={'a.md': [(10,'same','',''), (20,'same','','')]}
n,reused=sp_index.embed_and_store_diff(con,['a.md'],blocks,old_rows,0)
con.commit()
rows=con.execute('select count(*) from chunks').fetchone()[0]
vecs=con.execute('select count(*) from chunks where vec is not null').fetchone()[0]
print(f'{n},{reused},{rows},{vecs}')
PY
)
chk "$out" "0,2,2,2" "全部复用且两行都有向量"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

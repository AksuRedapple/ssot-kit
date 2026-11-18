#!/usr/bin/env python3
"""回归：sp_index_merge 兼容旧分片并保留 assertion 三列。"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import sp_index_merge  # noqa: E402


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        a, b, out = t / "a.db", t / "b.db", t / "out.db"
        con = sqlite3.connect(a)
        con.execute('create table chunks(id integer primary key, path text, line integer, text text, '
                    'role text, ts text, vec blob)')
        con.execute('create table src_state(path text primary key, digest text)')
        con.execute("insert into chunks values(1,'old.md',1,'x','','',NULL)")
        con.execute("insert into src_state values('old.md','d1')")
        con.commit(); con.close()
        con = sqlite3.connect(b)
        con.execute('create table chunks(id integer primary key, path text, line integer, text text, '
                    'role text, ts text, vec blob, assertion_id text, status text, superseded_by text)')
        con.execute('create table src_state(path text primary key, digest text)')
        con.execute("insert into chunks values(1,'knowledge/assertions.md',10,'x','assertion','',NULL,'A001','active',NULL)")
        con.execute("insert into src_state values('knowledge/assertions.md','d2')")
        con.commit(); con.close()
        sp_index_merge.merge(str(out), [str(a), str(b)])
        con = sqlite3.connect(out)
        cols = {r[1] for r in con.execute("pragma table_info(chunks)")}
        rows = con.execute("select assertion_id,status from chunks order by id").fetchall()
        n = con.execute("select count(*) from chunks").fetchone()[0]
        con.close()
        for c in ("assertion_id", "status", "superseded_by"):
            if c not in cols:
                fails.append(f"缺列 {c}")
        if n != 2 or ("A001", "active") not in rows:
            fails.append(f"合并结果不对: n={n} rows={rows}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   旧分片自动补三列")
    print("  ok   新分片 assertion 状态保留")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

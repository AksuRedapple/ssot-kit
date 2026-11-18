#!/usr/bin/env python3
"""回归：fetch_rows 读 status/superseded_by；旧库缺列不崩。"""
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import sp_semantic  # noqa: E402


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        db = t / "new.db"
        con = sqlite3.connect(db)
        con.execute('create table chunks(id integer primary key, path text, line integer, text text, '
                    'role text, ts text, vec blob, assertion_id text, status text, superseded_by text)')
        con.execute("insert into chunks values(1,'knowledge/assertions.md',10,'x','assertion','',NULL,'A012','superseded','A031')")
        con.commit(); con.close()
        d = sp_semantic.fetch_rows([1], db=str(db))
        if d.get(1, (None,) * 8)[5:] != ('A012', 'superseded', 'A031'):
            fails.append(f"新库字段不对: {d.get(1)}")

        old = t / "old.db"
        con = sqlite3.connect(old)
        con.execute('create table chunks(id integer primary key, path text, line integer, text text, '
                    'role text, ts text, vec blob)')
        con.execute("insert into chunks values(1,'lines/x.md',1,'x','','',NULL)")
        con.commit(); con.close()
        d = sp_semantic.fetch_rows([1], db=str(old))
        if len(d.get(1, ())) != 8 or d[1][7] is not None:
            fails.append(f"旧库回退不对: {d.get(1)}")

    rs = [{'score': 0.9, 'status': 'superseded', 'path': 'a'},
          {'score': 0.8, 'status': 'active', 'path': 'b'},
          {'score': 0.7, 'status': None, 'path': 'c'}]
    got = [r['path'] for r in sp_semantic.order_results(rs)]
    if got != ['b', 'c', 'a']:
        fails.append(f"排序不对: {got}")
    got = [r['path'] for r in sp_semantic.order_results(rs, active_only=True)]
    if got != ['b', 'c']:
        fails.append(f"active_only 不对: {got}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   新库读 assertion_id/status/superseded_by")
    print("  ok   旧库缺列回退 NULL")
    print("  ok   superseded 排后 / active_only 过滤")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

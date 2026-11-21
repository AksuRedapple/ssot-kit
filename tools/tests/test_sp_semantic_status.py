#!/usr/bin/env python3
"""回归：fetch_rows 读 status/superseded_by；旧库缺列不崩。"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import importlib.util
if importlib.util.find_spec("numpy") is None:
    print("skip: numpy not installed（读路径需要；写路径仍应可测）")
    sys.exit(77)   # 77 = SKIP（run_all 协议；0 会被当成 PASS，见 A562）
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

    # log_call: topk 写入 / --no-log 短路
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        old_log = sp_semantic.LOG
        sp_semantic.LOG = str(Path(td) / "log.jsonl")
        sp_semantic.log_call("sp_semantic", "q", 2, ("a", 1, 0.9), 10,
                             extra={"topk_paths": ["a", "b"], "topk_sids": ["11111111"]})
        line = _json.loads(open(sp_semantic.LOG, encoding="utf-8").read().splitlines()[-1])
        if line.get("topk_sids") != ["11111111"]:
            fails.append(f"topk 日志不对: {line}")
        os.environ["SSOT_NO_LOG"] = "1"
        sp_semantic.log_call("sp_semantic", "q2", 0, None, 1)
        n2 = len(open(sp_semantic.LOG, encoding="utf-8").read().splitlines())
        os.environ.pop("SSOT_NO_LOG", None)
        if n2 != 1:
            fails.append(f"--no-log 仍写: {n2}")
        sp_semantic.LOG = old_log

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

#!/usr/bin/env python3
"""回归：assertion_groups 一条一块/长块切分 + chunks 三列写入。"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "knowledge").mkdir()
        long_body = "长" * 1800
        (t / "knowledge/assertions.md").write_text(
            "## A001 · 活动断言\n- 状态：现役\n\n"
            "## A002 · 失效断言\n- 状态：已过时\nsuperseded_by: A001\n\n"
            "## A003 空号\n- 状态：空号\n\n"
            f"## A004 · 超长\n- 状态：现役\n{long_body}\n", encoding="utf-8")
        (t / "knowledge/assertions.meta.json").write_text(json.dumps({
            "schema": 1,
            "entries": {
                "A001": {"status": "active"},
                "A002": {"status": "superseded", "superseded_by": "A001"},
                "A003": {"status": "vacant"},
                "A004": {"status": "active"},
            },
        }), encoding="utf-8")
        os.environ["SSOT_ROOT"] = str(t)
        import sp_index
        groups = sp_index.assertion_groups()
        if len(groups) != 1:
            fails.append(f"assertion_groups 数量: {len(groups)}")
        else:
            rel, _digest, rows = groups[0]
            # A001/A002/A004；A003 vacant 跳过；A004 超长拆 2
            if len(rows) != 4:
                fails.append(f"rows 数不对（vacant/长块）: {len(rows)}")
            from sp_assert_lib import parse
            bs = {b["id"]: b for b in parse(str(t / "knowledge/assertions.md"))}
            if sp_index.ASSERT_META.get((rel, bs["A001"]["line"]))[1] != "active":
                fails.append(f"A001 meta 不对: {sp_index.ASSERT_META.get((rel, bs['A001']['line']))}")
            if sp_index.ASSERT_META.get((rel, bs["A002"]["line"]))[2] != "A001":
                fails.append(f"A002 superseded_by 不对: {sp_index.ASSERT_META.get((rel, bs['A002']['line']))}")
            con = sqlite3.connect(":memory:")
            con.execute('create table chunks(id integer primary key, path text, line integer, '
                        'text text, role text, ts text, vec blob, assertion_id text, status text, '
                        'superseded_by text)')
            sp_index.embed_batch = lambda texts: [[0.1] * 8 for _ in texts]
            sp_index.embed_and_store(con, [rel], {rel: rows}, 0)
            got = con.execute("select assertion_id,status,superseded_by from chunks order by id").fetchall()
            con.close()
            if ("A002", "superseded", "A001") not in got:
                fails.append(f"chunks 状态列不对: {got}")
        con = sqlite3.connect(":memory:")
        con.execute('create table chunks(id integer primary key, path text, text text)')
        sp_index.ensure_assertion_columns(con)
        cols = {r[1] for r in con.execute("pragma table_info(chunks)")}
        con.close()
        for c in ("assertion_id", "status", "superseded_by"):
            if c not in cols:
                fails.append(f"迁移缺列 {c}: {cols}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   vacant 跳过 / 长块二次切分")
    print("  ok   assertion_id/status/superseded_by 写入")
    print("  ok   旧 chunks 表可补三列")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

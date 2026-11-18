#!/usr/bin/env python3
"""回归：coverage 把 policy 跳过单列，不算缺口（2026-11-18）。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_coverage.py"


def mk_s1(root, sid, cls, title):
    d = root / "evidence" / "qoder" / "S1-sessions" / f"2026-01-01-{sid[:8]}-{title}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"sid": sid, "title": title, "session_class": cls}, ensure_ascii=False), encoding="utf-8")
    (d / "transcript.jsonl").write_text(json.dumps({"role": "user", "content": "x" * 3000}) + "\n", encoding="utf-8")
    return d


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "profile").mkdir()
        (t / "profile/index-policy.json").write_text(json.dumps({
            "schema": 1, "enabled": True,
            "include": ["human", "decision", "unknown"],
            "skip": ["automation", "monitor"], "rules": [],
        }), encoding="utf-8")
        d1 = mk_s1(t, "11111111-0000-4000-8000-000000000000", "monitor", "值守")
        d2 = mk_s1(t, "22222222-0000-4000-8000-000000000000", "human", "正常")
        dbp = t / "S2-index/semantic/index.db"
        dbp.parent.mkdir(parents=True)
        con = sqlite3.connect(dbp)
        con.execute('create table chunks(id integer primary key, path text, text text)')
        rel = os.path.relpath(d2 / "transcript.jsonl", t)
        con.execute('insert into chunks(path,text) values(?,?)', (rel, 'x'))
        con.commit(); con.close()

        env = dict(os.environ, SSOT_ROOT=str(t))
        r = subprocess.run([sys.executable, str(TOOL), "--json"], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            q = next(x for x in d["sources"] if x["src"] == "qoder")
            if q["s1"] != 2 or q["skipped"] != 1 or q["need"] != 1 or q["covered"] != 1:
                fails.append(f"qoder 计数不对: {q}")
            if q["status"] != "ok":
                fails.append(f"status 应为 ok: {q}")
        r = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, env=env)
        if "跳过" not in r.stdout or "策略跳过 1" not in r.stdout:
            fails.append(f"表/结论未显示跳过: {r.stdout}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   skipped=1 / need=1 / covered=1 / ok")
    print("  ok   表与结论显示策略跳过")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

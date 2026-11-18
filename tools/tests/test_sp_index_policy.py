#!/usr/bin/env python3
"""回归：sp_index --plan / --apply-policy 按 session_class 过滤，human 不受影响。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_index.py"


def mk_s1(root, sid, cls, title):
    d = root / "evidence" / "qoder" / "S1-sessions" / f"2026-01-01-{sid[:8]}-{title}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"sid": sid, "title": title, "cwd": "/tmp", "session_class": cls},
        ensure_ascii=False), encoding="utf-8")
    (d / "transcript.jsonl").write_text('{"role":"user","kind":"text","t":"2026-01-01T00:00:00Z","content":"正常内容 abcdefghij"}\n', encoding="utf-8")
    return d


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


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
        (t / "profile/contract.json").write_text('{"contract": 2}\n', encoding="utf-8")
        d1 = mk_s1(t, "11111111-0000-4000-8000-000000000000", "monitor", "值守")
        d2 = mk_s1(t, "22222222-0000-4000-8000-000000000000", "human", "正常")
        dbp = t / "S2-index/semantic/index.db"
        dbp.parent.mkdir(parents=True)
        con = sqlite3.connect(dbp)
        con.execute('create table chunks(id integer primary key, path text, line integer, '
                    'text text, role text, ts text, vec blob)')
        con.execute('create table src_state(path text primary key, digest text)')
        for d, n in ((d1, 3), (d2, 4)):
            rel = os.path.relpath(d / "transcript.jsonl", t)
            for i in range(n):
                con.execute('insert into chunks(path,line,text,role,ts,vec) values(?,?,?,?,?,?)',
                            (rel, i, 'x', 'user', '2026-01-01', b''))
            con.execute('insert into src_state values(?,?)', (rel, 'old'))
        con.commit(); con.close()

        r = run(t, "--plan")
        if r.returncode != 0 or "skip:    1 源" not in r.stdout:
            fails.append(f"plan 未跳过 monitor: rc={r.returncode}\n{r.stdout}\n{r.stderr}")
        if "would remove: 3 块" not in r.stdout:
            fails.append(f"plan 未算 would remove: {r.stdout}")

        r = run(t, "--apply-policy")
        if r.returncode != 0:
            fails.append(f"apply-policy rc={r.returncode}: {r.stderr}")
        con = sqlite3.connect(dbp)
        n1 = con.execute('select count(*) from chunks where path like ?', ('%11111111%',)).fetchone()[0]
        n2 = con.execute('select count(*) from chunks where path like ?', ('%22222222%',)).fetchone()[0]
        con.close()
        if n1 != 0 or n2 != 4:
            fails.append(f"删除范围不对: monitor={n1} human={n2}")
        if not (t / "logs/index-ops.jsonl").exists():
            fails.append("缺 index-ops 审计")
        bj = t / "S2-index/semantic/BUILD.json"
        if not bj.exists():
            fails.append("apply-policy 未刷新 BUILD.json")
        else:
            b = json.loads(bj.read_text())
            if b.get("chunks") != 4 or b.get("policy", {}).get("skipped_sources") != 1:
                fails.append(f"BUILD policy 读数不对: {b}")

        r = run(t, "--plan", "--all-classes")
        if "skip:    0 源" not in r.stdout:
            fails.append(f"--all-classes 仍跳过: {r.stdout}")

        r = run(t, "--plan", "--class", "human")
        if "skip:    1 源" not in r.stdout:
            fails.append(f"--class human 未跳过 monitor: {r.stdout}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   --plan 显示 skip/would remove")
    print("  ok   --apply-policy 只删 monitor")
    print("  ok   --all-classes / --class 覆盖")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

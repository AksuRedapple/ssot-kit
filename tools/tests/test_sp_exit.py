#!/usr/bin/env python3
"""回归：sp_exit 稳定 sid manifest / retire / verify / 幂等 / unretire / sp_index 不复活。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXIT = ROOT / "tools" / "sp_exit.py"
INDEX = ROOT / "tools" / "sp_index.py"


def mk_s1(root, sid, cls, title):
    d = root / "evidence" / "qoder" / "S1-sessions" / f"2026-01-01-{sid[:8]}-{title}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"sid": sid, "title": title, "cwd": "/tmp", "session_class": cls},
        ensure_ascii=False), encoding="utf-8")
    (d / "transcript.jsonl").write_text(
        '{"role":"user","kind":"text","t":"2026-01-01T00:00:00Z","content":"内容 abcdefghij"}\n',
        encoding="utf-8")
    return d


def run(tool, root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "profile").mkdir()
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

        man = t / "logs/exit.jsonl"
        r = run(EXIT, t, "--make-manifest", "--class", "monitor", "--out", str(man))
        if r.returncode != 0 or not man.exists():
            fails.append(f"make-manifest rc={r.returncode}: {r.stderr}")
        else:
            lines = [json.loads(x) for x in man.read_text().splitlines() if x.strip()]
            if len(lines) != 2 or lines[1]["blocks"] != 3:
                fails.append(f"manifest 内容不对: {lines}")

        r = run(EXIT, t, "--retire", str(man), "--reason", "测试", "--apply")
        if r.returncode != 0:
            fails.append(f"retire rc={r.returncode}: {r.stderr}")
        con = sqlite3.connect(dbp)
        n1 = con.execute('select count(*) from chunks where path like ?', ('%11111111%',)).fetchone()[0]
        n2 = con.execute('select count(*) from chunks where path like ?', ('%22222222%',)).fetchone()[0]
        con.close()
        if n1 != 0 or n2 != 4:
            fails.append(f"retire 删除范围不对: monitor={n1} human={n2}")

        r = run(EXIT, t, "--verify", str(man))
        if r.returncode != 0:
            fails.append(f"verify 应 PASS: rc={r.returncode} {r.stdout}")

        before = (t / "profile/retired.jsonl").read_text()
        r = run(EXIT, t, "--retire", str(man), "--reason", "测试", "--apply")
        after = (t / "profile/retired.jsonl").read_text()
        if before != after:
            fails.append("重复 retire 不幂等（retired.jsonl 变长）")

        # sp_index --plan 必须把 retired 跳过（即使 class=human）
        r = run(INDEX, t, "--plan")
        if "skip:    1 源" not in r.stdout:
            fails.append(f"sp_index 未跳过 retired: {r.stdout}")

        r = run(EXIT, t, "--unretire", "11111111", "--apply")
        if r.returncode != 0:
            fails.append(f"unretire rc={r.returncode}: {r.stderr}")
        r = run(EXIT, t, "--verify", str(man))
        if r.returncode != 1:
            fails.append(f"unretire 后 verify 应 FAIL，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   manifest 用 sid 且带块数")
    print("  ok   retire 只删目标 / verify PASS")
    print("  ok   重复 retire 幂等")
    print("  ok   sp_index --plan 跳过 retired")
    print("  ok   unretire 后 verify FAIL")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

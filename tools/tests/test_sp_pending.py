#!/usr/bin/env python3
"""回归：pending-index 合并/决策/清标记（不跑真实索引）。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_pending.py"


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "S2-index/semantic").mkdir(parents=True)
        db = t / "S2-index/semantic/index.db"
        con = sqlite3.connect(db)
        con.execute("create table chunks(id integer primary key, path text, line integer, text text, role text, ts text, vec blob)")
        con.execute("create table src_state(path text primary key, digest text)")
        con.commit(); con.close()
        s1 = t / "evidence/qoder/S1-sessions/2026-01-01-11111111-x"
        s1.mkdir(parents=True)
        (s1 / "meta.json").write_text(json.dumps({"sid": "11111111-0000-4000-8000-000000000000", "title": "x", "start": "2026-01-01T00:00:00Z"}), encoding="utf-8")
        (s1 / "transcript.jsonl").write_text(json.dumps({"role": "user", "kind": "text", "t": "2026-01-01T00:00:00Z", "content": "x" * 3000}) + "\n", encoding="utf-8")

        r = run(t, "--merge", "--sessions", "2", "--est-blocks", "100", "--by-session", "s1", "--json")
        if r.returncode != 0:
            fails.append(f"merge rc={r.returncode}: {r.stderr}")
        r = run(t, "--status", "--json")
        d = json.loads(r.stdout)
        if d.get("sessions") != 2 or d.get("est_blocks") != 100 or d.get("generation") != 1:
            fails.append(f"marker 不对: {d}")

        r = run(t, "--decide", "--threshold", "1", "--json")
        d = json.loads(r.stdout)
        if d.get("action") != "defer" or d.get("pending_blocks", 0) <= 0:
            fails.append(f"阈值决策不对: {d}")
        r = run(t, "--decide", "--force", "--json")
        if json.loads(r.stdout).get("action") != "run":
            fails.append(f"force 决策不对: {r.stdout}")

        # after_index: generation 未变 → 清 marker
        env = dict(os.environ, SSOT_ROOT=str(t))
        code = ("import sys;sys.path.insert(0,%r);from ssotlib import pending;"
                "d=pending.load();pending.after_index(d.get('generation'),False,False);"
                "print(pending.load())" % str(ROOT / "tools"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        if r.returncode != 0 or json.loads(r.stdout):
            fails.append(f"after_index 未清: {r.stdout} {r.stderr}")

        # pending 仍有内容时 clear-if-settled 保留
        run(t, "--merge", "--sessions", "1", "--est-blocks", "10")
        r = run(t, "--clear-if-settled", "--json")
        if json.loads(r.stdout).get("cleared"):
            fails.append("pending>0 时不应清除")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   merge/status/generation")
    print("  ok   threshold defer / force run")
    print("  ok   after_index 清 / pending 未清")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

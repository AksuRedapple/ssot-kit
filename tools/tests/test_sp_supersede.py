#!/usr/bin/env python3
"""回归：supersede propose/confirm/from-conflict（append-only + meta）。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_supersede.py"


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "knowledge").mkdir(parents=True)
        (t / "knowledge/assertions.md").write_text(
            "## A001 · 旧\n- 状态：现役\n\n## A002 · 新\n- 状态：现役\n", encoding="utf-8")
        (t / "inbox/candidates").mkdir(parents=True)
        (t / "inbox/candidates/candidates.jsonl").write_text(json.dumps(
            {"id": "c1", "state": "conflict", "assertion": "A001", "claim": "旧结论是错的"},
            ensure_ascii=False) + "\n", encoding="utf-8")

        r = run(t, "--from-conflict", "--json")
        if r.returncode != 0 or json.loads(r.stdout)["count"] != 1:
            fails.append(f"from-conflict 不对: {r.returncode} {r.stdout}")

        r = run(t, "--propose", "A001", "--by", "A002", "--apply")
        if r.returncode != 0 or not (t / "knowledge/supersede-events.jsonl").exists():
            fails.append(f"propose 失败: {r.returncode} {r.stderr}")
        if (t / "knowledge/assertions.meta.json").exists():
            fails.append("propose 不应改 meta")

        r = run(t, "--confirm", "A001", "--by", "A002", "--apply")
        if r.returncode != 0:
            fails.append(f"confirm 失败: {r.returncode} {r.stderr}")
        meta = json.loads((t / "knowledge/assertions.meta.json").read_text())
        e = meta["entries"]["A001"]
        if e.get("status") != "superseded" or e.get("superseded_by") != "A002":
            fails.append(f"meta 不对: {e}")

        r = run(t, "--list", "--json")
        if json.loads(r.stdout)["count"] != 2:
            fails.append(f"events 数量不对: {r.stdout}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   from-conflict 只读")
    print("  ok   propose append-only，不改 meta")
    print("  ok   confirm 写 status/superseded_by + 事件")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

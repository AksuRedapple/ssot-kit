#!/usr/bin/env python3
"""回归：assertions.meta sidecar scan/apply/set 幂等。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_assert_meta.py"


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "knowledge").mkdir(parents=True)
        (t / "knowledge/assertions.md").write_text(
            "## A001 · 活动\n- 状态：现役\n\n"
            "## A002 · 失效\n- 状态：已过时\n\n"
            "## A003 · 缺状态\n- 标签：x\n", encoding="utf-8")
        r = run(t, "--scan", "--json")
        d = json.loads(r.stdout)
        if d["status_counts"].get("active") != 1 or d["status_counts"].get("superseded") != 1 or d["status_counts"].get("unknown") != 1:
            fails.append(f"状态计数不对: {d['status_counts']}")
        r = run(t, "--apply")
        meta = json.loads((t / "knowledge/assertions.meta.json").read_text())
        if meta["entries"]["A002"]["status"] != "superseded":
            fails.append(f"meta 不对: {meta['entries'].get('A002')}")
        r = run(t, "--scan", "--json")
        if json.loads(r.stdout)["changed"] != 0:
            fails.append("二次 scan 不幂等")
        r = run(t, "--set", "A003", "--status", "active", "--reason", "补状态")
        if r.returncode != 0:
            fails.append(f"set 失败: {r.stderr}")
        meta = json.loads((t / "knowledge/assertions.meta.json").read_text())
        if meta["entries"]["A003"].get("source") != "manual":
            fails.append(f"manual 未记: {meta['entries'].get('A003')}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   scan 状态映射 / unknown")
    print("  ok   apply 幂等")
    print("  ok   set 手工覆盖")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

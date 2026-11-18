#!/usr/bin/env python3
"""回归：S0 巡检只报计数/路径，不输出密钥内容。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_s0scan.py"
SECRET = "sk-" + "a" * 32


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        s0 = t / "evidence/qoder/S0-archive/proj"
        s0.mkdir(parents=True)
        (s0 / "a.jsonl").write_text('{"x":"%s"}\n' % SECRET, encoding="utf-8")
        (s0 / "b.jsonl").write_text('{"x":"clean"}\n', encoding="utf-8")
        pi = t / "evidence/pi/S0-archive/proj"
        pi.mkdir(parents=True)
        (pi / "c.jsonl").write_text('{"x":"%s"}\n' % SECRET, encoding="utf-8")
        env = dict(os.environ, SSOT_ROOT=str(t))
        r = subprocess.run([sys.executable, str(TOOL), "--json", "--write-state"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            if d["files_hit"] != 2 or d["matches"] < 2:
                fails.append(f"计数不对: {d}")
            if SECRET in r.stdout or "sk-aaa" in r.stdout:
                fails.append("输出了密钥内容")
        r = subprocess.run([sys.executable, str(TOOL), "--json", "--only", "pi"],
                           capture_output=True, text=True, env=env)
        d = json.loads(r.stdout)
        if d["scanned"] != 1 or d["files_hit"] != 1:
            fails.append(f"--only pi 不对: {d}")
        st = t / "alerts/s0-scan.json"
        if not st.exists() or json.loads(st.read_text())["files_hit"] != 2:
            fails.append("state 未写/不对")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   S0 命中计数")
    print("  ok   不输出密钥内容")
    print("  ok   state 写入")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

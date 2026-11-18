#!/usr/bin/env python3
"""回归：sp_drafts 只读、候选行 10 字段、无 S1 时拒绝转正（2026-11-18）。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_drafts.py"
SID = "1a2b3c4d-0000-4000-8000-000000000000"


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pend = root / "sessions" / "_pending"
        pend.mkdir(parents=True)
        (pend / "1a2b3c4d.md").write_text(
            "- 2026-11-18 10:00:00 | sid: %s | cwd: /tmp/demo\n" % SID, encoding="utf-8")
        s1 = root / "evidence" / "qoder" / "S1-sessions" / "2026-11-18-1a2b3c4d-demo"
        s1.mkdir(parents=True)
        (s1 / "meta.json").write_text(json.dumps({
            "sid": SID, "title": "演示会话", "cwd": "/tmp/demo",
            "start": "2026-11-18T10:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8")
        (s1 / "transcript.jsonl").write_text(
            json.dumps({"role": "user", "kind": "text", "content": "第一条用户消息"}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        reg = root / "sessions" / "registry.md"
        reg.write_text("# registry\n- KEEP\n", encoding="utf-8")
        before = reg.read_bytes()

        r = run(root, "--list", "--json")
        if r.returncode != 0:
            fails.append(f"--list rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            if d.get("pending") != 1 or not d["rows"][0].get("has_s1"):
                fails.append(f"--list 结果不对: {d}")

        r = run(root, "--candidate", "1a2b3c4d")
        if r.returncode != 0:
            fails.append(f"--candidate rc={r.returncode}: {r.stderr}")
        else:
            line = r.stdout.strip()
            if line.count("|") != 9:
                fails.append(f"不是 10 字段: {line}")
            for want in (SID, "演示会话", "line:待归类", "第一条用户消息"):
                if want not in line:
                    fails.append(f"候选行缺 {want}: {line}")
        if reg.read_bytes() != before:
            fails.append("候选生成改动了 registry")

        (s1 / "meta.json").unlink()
        r = run(root, "--candidate", "1a2b3c4d")
        if r.returncode != 2:
            fails.append(f"无 S1 应 rc=2，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   --list 与草稿数一致")
    print("  ok   候选行为 10 字段且不改 registry")
    print("  ok   无 S1 时拒绝转正（rc=2）")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

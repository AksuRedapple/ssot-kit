#!/usr/bin/env python3
"""回归：sp_golden capture/check（用假 sp_semantic，不依赖模型）。"""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_golden.py"


def write_fake(root, path):
    f = root / "tools" / "sp_semantic.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("#!/usr/bin/env python3\n"
                 "import sys\n"
                 f"print('[0.900] {path}:1  假命中')\n", encoding="utf-8")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root))
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "lines").mkdir()
        (t / "lines/demo.md").write_text("# 演示线的稳定问题\n", encoding="utf-8")
        r = run(t, "--init")
        if r.returncode != 0 or not (t / "profile/golden-queries.jsonl").exists():
            fails.append(f"--init 未建模板: {r.returncode} {r.stderr}")
        r = run(t, "--suggest", "--json")
        if r.returncode != 0 or "演示线的稳定问题" not in r.stdout:
            fails.append(f"--suggest 未出候选: {r.returncode} {r.stdout} {r.stderr}")
        if (t / "profile/golden-baseline.json").exists():
            fails.append("--suggest 不应写基线")

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "profile").mkdir()
        (t / "profile/golden-queries.jsonl").write_text(
            json.dumps({"id": "g1", "query": "测试问题", "expect_sids": ["11111111"]},
                       ensure_ascii=False) + "\n", encoding="utf-8")
        write_fake(t, "evidence/qoder/S1-sessions/2026-01-01-11111111-x/transcript.jsonl")
        r = run(t, "--capture", "--apply")
        if r.returncode != 0 or not (t / "profile/golden-baseline.json").exists():
            fails.append(f"capture rc={r.returncode}: {r.stderr}")
        r = run(t, "--check", "--json")
        if r.returncode != 0 or not json.loads(r.stdout)["ok"]:
            fails.append(f"check 应 PASS: {r.returncode} {r.stdout} {r.stderr}")
        write_fake(t, "evidence/qoder/S1-sessions/2026-01-01-22222222-y/transcript.jsonl")
        r = run(t, "--check", "--json")
        if r.returncode != 1:
            fails.append(f"换路径应 FAIL，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   --init/--suggest 不写基线")
    print("  ok   capture 写基线")
    print("  ok   相同命中 PASS")
    print("  ok   命中漂移 FAIL")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""回归：session_class 规则扫描/写入/幂等/手工覆盖（2026-11-18）。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_classify.py"


def mk_s1(root, sid, title, cwd, harness="qoder"):
    d = root / "evidence" / harness / "S1-sessions" / f"2026-01-01-{sid[:8]}-{title}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"sid": sid, "title": title, "cwd": cwd}, ensure_ascii=False), encoding="utf-8")
    (d / "transcript.jsonl").write_text('{"role":"user","content":"x"}\n', encoding="utf-8")
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
            "skip": ["automation", "monitor"],
            "rules": [
                {"match": {"harness": "qoder", "title_regex": "值守"}, "class": "monitor",
                 "reason": "title 命中值守"},
                {"match": {"cwd_regex": "/auto/"}, "class": "automation", "reason": "cwd auto"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        d1 = mk_s1(t, "11111111-0000-4000-8000-000000000000", "钉钉值守", "/tmp/monitor")
        d2 = mk_s1(t, "22222222-0000-4000-8000-000000000000", "正常线", "/tmp/work")

        r = run(t, "--scan", "--json")
        if r.returncode != 0:
            fails.append(f"scan rc={r.returncode}: {r.stderr}")
        else:
            rows = {x["sid"][:8]: x for x in json.loads(r.stdout)["rows"]}
            if rows["11111111"]["class"] != "monitor":
                fails.append(f"规则未命中: {rows['11111111']}")
            if rows["22222222"]["class"] != "human":
                fails.append(f"默认不是 human: {rows['22222222']}")

        r = run(t, "--apply")
        if r.returncode != 0:
            fails.append(f"apply rc={r.returncode}: {r.stderr}")
        m1 = json.loads((d1 / "meta.json").read_text())
        if m1.get("session_class") != "monitor" or m1.get("class_source") != "rule":
            fails.append(f"meta 未写入: {m1}")

        r = run(t, "--apply", "--json")
        if json.loads(r.stdout)["changed"] != 0:
            fails.append(f"二次 apply 不幂等: {r.stdout}")

        r = run(t, "--set", "22222222", "--class", "decision", "--reason", "人工确认")
        if r.returncode != 0:
            fails.append(f"set rc={r.returncode}: {r.stderr}")
        m2 = json.loads((d2 / "meta.json").read_text())
        if m2.get("session_class") != "decision" or m2.get("class_source") != "manual":
            fails.append(f"手工覆盖未生效: {m2}")

        r = run(t, "--apply")
        m2 = json.loads((d2 / "meta.json").read_text())
        if m2.get("session_class") != "decision":
            fails.append(f"重新 apply 覆盖了手工分类: {m2}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   规则命中 monitor / 默认 human")
    print("  ok   apply 写入 meta 且幂等")
    print("  ok   手工覆盖保持")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

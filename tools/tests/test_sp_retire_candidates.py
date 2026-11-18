#!/usr/bin/env python3
"""回归：P4 零命中选择只读、按 topk_sids/top1_path 聚合。"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_retire_candidates.py"


def mk(root, sid, title):
    d = root / "evidence/qoder/S1-sessions" / f"2026-01-01-{sid[:8]}-{title}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps(
        {"sid": sid, "title": title, "start": "2026-01-01T00:00:00Z"},
        ensure_ascii=False), encoding="utf-8")


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "S2-index").mkdir()
        mk(t, "11111111-0000-4000-8000-000000000000", "有命中")
        mk(t, "22222222-0000-4000-8000-000000000000", "零命中")
        ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        (t / "S2-index/search-log.jsonl").write_text(json.dumps(
            {"ts": ts, "tool": "sp_semantic", "query": "q",
             "topk_sids": ["11111111"]}, ensure_ascii=False) + "\n", encoding="utf-8")
        env = dict(os.environ, SSOT_ROOT=str(t))
        r = subprocess.run([sys.executable, str(TOOL), "--days", "30", "--json"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            ids = [x["sid8"] for x in d["candidates"]]
            if "22222222" not in ids or "11111111" in ids:
                fails.append(f"候选不对: {ids}")
            if d["logs"] != 1:
                fails.append(f"logs 不对: {d['logs']}")
            if not d.get("low_confidence"):
                fails.append(f"日志不足应标低置信: {d}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   topk_sids 命中被排除")
    print("  ok   零命中会话进候选")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

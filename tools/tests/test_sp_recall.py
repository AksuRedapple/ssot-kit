#!/usr/bin/env python3
"""回归：sp_recall 不依赖索引、S0 输出脱敏、S1/S0/live 三层可用。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_recall.py"
SECRET = "sk-" + "a" * 32  # 运行时拼接，避免公开面审计把它当真实密钥


def run(env, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        s1 = t / "ssot/evidence/qoder/S1-sessions/2026-01-01-1a2b3c4d-demo"
        s1.mkdir(parents=True)
        (s1 / "transcript.jsonl").write_text(
            json.dumps({"t": "2026-01-01T10:00:00Z", "role": "user", "kind": "text",
                        "content": "alpha needle beta"}, ensure_ascii=False) + "\n" +
            json.dumps({"t": "2026-01-01T10:01:00Z", "role": "assistant", "kind": "text",
                        "content": "有密钥 %s" % SECRET}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        s0 = t / "ssot/evidence/qoder/S0-archive/proj"
        s0.mkdir(parents=True)
        (s0 / "1a2b3c4d.jsonl").write_text(
            json.dumps({"message": {"role": "user", "content": "rawneedle %s" % SECRET}},
                       ensure_ascii=False) + "\n", encoding="utf-8")
        live = t / "live/proj"
        live.mkdir(parents=True)
        (live / "liveonly.jsonl").write_text(
            json.dumps({"message": {"role": "user", "content": "liveonly phrase"}},
                       ensure_ascii=False) + "\n", encoding="utf-8")
        env = dict(os.environ, SSOT_ROOT=str(t / "ssot"), SSOT_CC_ROOT=str(t / "live"),
                   SSOT_QODER_ROOT=str(t / "none"), SSOT_QODERWORK_ROOT=str(t / "none"),
                   SSOT_DSH_ROOT=str(t / "none"), SSOT_PI_ROOT=str(t / "none"),
                   SSOT_CODEX_ROOT=str(t / "none"))
        # 没有 S2-index 也必须可用
        r = run(env, "needle", "--json")
        if r.returncode != 0:
            fails.append(f"S1 查询 rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            if d["count"] != 1 or d["hits"][0]["layer"] != "S1":
                fails.append(f"S1 命中不对: {d}")
            if d["hits"][0]["sid"] != "1a2b3c4d":
                fails.append(f"sid 解析不对: {d['hits'][0]['sid']}")

        r = run(env, "rawneedle", "--raw", "--json")
        if r.returncode != 0:
            fails.append(f"S0 查询 rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            hit = d["hits"][0] if d["hits"] else {}
            if hit.get("layer") != "S0" or SECRET in hit.get("snippet", ""):
                fails.append(f"S0 未命中或未脱敏: {hit}")
            elif "[REDACTED-SECRET]" not in hit.get("snippet", ""):
                fails.append(f"脱敏标记缺失: {hit.get('snippet')}")

        r = run(env, "liveonly", "--live", "--json")
        if r.returncode != 0 or json.loads(r.stdout)["hits"][0]["layer"] != "live":
            fails.append(f"live 查询失败: rc={r.returncode} {r.stdout}")

        r = run(env, "no-such-token-xyz")
        if r.returncode != 1:
            fails.append(f"无命中应 rc=1，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   S1 命中 + sid 解析")
    print("  ok   无索引仍可用")
    print("  ok   S0 命中且密钥脱敏")
    print("  ok   live 真源可用")
    print("  ok   无命中 rc=1")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

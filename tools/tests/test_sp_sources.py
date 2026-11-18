#!/usr/bin/env python3
"""回归：sp_sources 发现 harness 真源，不拿 evidence/ 当归档分母（2026-11-18）。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_sources.py"


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        for rel in ("qoder/proj", "cc/proj", "dsh/proj/sid", "pi/proj", "codex/2026"):
            (t / rel).mkdir(parents=True, exist_ok=True)
        (t / "qoder/proj/a.jsonl").write_text("{}\n")
        (t / "cc/proj/b.jsonl").write_text("{}\n")
        (t / "dsh/proj/sid/session.v4.jsonl.zstd").write_text("z")
        (t / "pi/proj/c.jsonl").write_text("{}\n")
        (t / "codex/2026/d.jsonl").write_text("{}\n")
        appdb = t / "main.sqlite"
        con = sqlite3.connect(appdb)
        con.execute("create table chat_sessions(session_id text)")
        con.execute("insert into chat_sessions values ('x')")
        con.commit()
        con.close()

        env = dict(os.environ,
                   SSOT_ROOT=str(t / "ssot"),
                   SSOT_QODER_ROOT=str(t / "qoder"),
                   SSOT_QODERWORK_ROOT=str(t / "no-qoderwork"),
                   SSOT_CC_ROOT=str(t / "cc"),
                   SSOT_DSH_ROOT=str(t / "dsh"),
                   SSOT_PI_ROOT=str(t / "pi"),
                   SSOT_CODEX_ROOT=str(t / "codex"),
                   SSOT_QODER_APP_DB=str(appdb))
        r = subprocess.run([sys.executable, str(TOOL), "--json", "--only", "qoder,cc,dsh,pi,codex,qoder-app"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            rows = {x["src"]: x for x in json.loads(r.stdout)["sources"]}
            for src, n in (("qoder", 1), ("cc", 1), ("dsh", 1), ("pi", 1), ("codex", 1)):
                if src not in rows or rows[src]["sessions"] != n:
                    fails.append(f"{src} 会话数不对: {rows.get(src)}")
            if rows.get("qoder-app", {}).get("sessions") != 1:
                fails.append(f"qoder-app sqlite 未计入: {rows.get('qoder-app')}")
            if rows["cc"]["roots"][0]["dest"] != "evidence/cc/S0-archive/claude-projects":
                fails.append(f"cc 归档目标不对: {rows['cc']['roots'][0]['dest']}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   四类 jsonl 源各发现 1 个会话")
    print("  ok   qoder-app sqlite 计入发现数")
    print("  ok   归档目标路径正确")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

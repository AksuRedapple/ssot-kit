#!/usr/bin/env python3
"""回归：sp_archive 默认不写、hardlink 优先、跑两次不新增、更新只改变动文件。"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_archive.py"


def run(env, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def summary(out):
    return json.loads(out)["summary"]


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        live = t / "live"
        (live / "proj").mkdir(parents=True)
        (live / "proj/a.jsonl").write_text('{"x":1}\n')
        (live / "proj/b.jsonl").write_text('{"x":2}\n')
        env = dict(os.environ,
                   SSOT_ROOT=str(t / "ssot"),
                   SSOT_CC_ROOT=str(live))

        r = run(env, "--only", "cc", "--settle", "0", "--json")
        if r.returncode != 0:
            fails.append(f"dry rc={r.returncode}: {r.stderr}")
        elif summary(r.stdout)["new"] != 2:
            fails.append(f"dry 新增数不对: {summary(r.stdout)}")
        if (t / "ssot/evidence/cc/S0-archive/claude-projects/proj/a.jsonl").exists():
            fails.append("dry-run 写了文件")

        r = run(env, "--only", "cc", "--settle", "0", "--apply", "--json")
        s1 = summary(r.stdout)
        if r.returncode != 0 or s1["new"] != 2 or s1["link"] != 2:
            fails.append(f"首次归档不对: rc={r.returncode} {s1}")
        dst = t / "ssot/evidence/cc/S0-archive/claude-projects/proj/a.jsonl"
        if not dst.exists() or os.stat(dst).st_ino != os.stat(live / "proj/a.jsonl").st_ino:
            fails.append("未使用 hardlink（inode 不同）")
        man = t / "ssot/logs/archive-manifest.jsonl"
        n1 = len(man.read_text().splitlines()) if man.exists() else 0

        r = run(env, "--only", "cc", "--settle", "0", "--apply", "--json")
        s2 = summary(r.stdout)
        if s2["new"] or s2["update"]:
            fails.append(f"第二次仍新增/更新: {s2}")
        n2 = len(man.read_text().splitlines()) if man.exists() else 0
        if n1 != n2:
            fails.append(f"幂等运行仍写 manifest: {n1}→{n2}")

        # --copy 必须把既有 hardlink 重新落成实体副本
        r = run(env, "--only", "cc", "--settle", "0", "--apply", "--copy", "--json")
        sc = summary(r.stdout)
        if r.returncode != 0 or sc["copy"] != 2:
            fails.append(f"--copy 未重写: rc={r.returncode} {sc}")
        if os.stat(dst).st_ino == os.stat(live / "proj/a.jsonl").st_ino:
            fails.append("--copy 仍是 hardlink")

        # 源被 harness 整体替换（新 inode）→ 归档要更新
        tmp = live / "proj/a.new"
        tmp.write_text('{"x":1,"changed":true}\n')
        os.replace(tmp, live / "proj/a.jsonl")
        os.utime(live / "proj/a.jsonl", (time.time(), time.time()))
        r = run(env, "--only", "cc", "--settle", "0", "--apply", "--json")
        s3 = summary(r.stdout)
        if s3["update"] != 1:
            fails.append(f"变更未更新: {s3}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   dry-run 不写")
    print("  ok   首次归档 hardlink（同 inode）")
    print("  ok   二次运行 0 新增 / manifest 不膨胀")
    print("  ok   源变更 → update 1")
    print("  ok   --copy 回退实体复制")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

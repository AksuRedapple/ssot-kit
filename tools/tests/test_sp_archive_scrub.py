#!/usr/bin/env python3
"""回归：sp_archive --scrub 是 copy-on-write，源文件字节不变，幂等。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_archive.py"
SECRET = "sk-" + "a" * 32


def run(root, *args):
    env = dict(os.environ, SSOT_ROOT=str(root / "ssot"), SSOT_CC_ROOT=str(root / "live"),
               SSOT_QODER_ROOT=str(root / "none"), SSOT_QODERWORK_ROOT=str(root / "none"),
               SSOT_DSH_ROOT=str(root / "none"), SSOT_PI_ROOT=str(root / "none"),
               SSOT_CODEX_ROOT=str(root / "none"))
    return subprocess.run([sys.executable, str(TOOL), "--only", "cc", "--settle", "0", *args],
                          capture_output=True, text=True, env=env)


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        live = t / "live/proj"
        live.mkdir(parents=True)
        secret_file = live / "a.jsonl"
        original = ('{"role":"user","content":"key %s"}\n' % SECRET).encode()
        secret_file.write_bytes(original)
        plain = live / "b.jsonl"
        plain.write_text('{"role":"user","content":"plain"}\n', encoding="utf-8")
        binary = live / "c.jsonl"
        binary.write_bytes(b"\xff\xfe\x00\x01")

        # 先建 hardlink 归档
        r = run(t, "--apply")
        if r.returncode != 0:
            fails.append(f"初始归档 rc={r.returncode}: {r.stderr}")
        dst = t / "ssot/evidence/cc/S0-archive/claude-projects/proj/a.jsonl"
        if os.stat(dst).st_ino != os.stat(secret_file).st_ino:
            fails.append("初始归档不是 hardlink")

        # scrub：必须断开 hardlink、源字节不变
        r = run(t, "--scrub", "--apply", "--json")
        if r.returncode != 0:
            fails.append(f"scrub rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            if d["summary"]["scrub"] < 1:
                fails.append(f"scrub 计数不对: {d['summary']}")
            rec = [x for x in d["records"] if x.get("scrubbed") and x.get("src_path", "").endswith("a.jsonl")][0]
            if rec.get("sensitivity") != "high" or rec.get("redactions", 0) < 1:
                fails.append(f"manifest 字段不对: {rec}")
        if secret_file.read_bytes() != original:
            fails.append("scrub 改了源文件（严重）")
        if SECRET.encode() in dst.read_bytes():
            fails.append("目标仍含密钥")
        if b"[REDACTED-SECRET]" not in dst.read_bytes():
            fails.append("目标没有脱敏标记")
        if os.stat(dst).st_ino == os.stat(secret_file).st_ino:
            fails.append("scrub 后仍是 hardlink")

        # 幂等：第二次 scrub 不再重写
        before = dst.read_bytes()
        r = run(t, "--scrub", "--apply", "--json")
        d = json.loads(r.stdout)
        if d["summary"]["scrub"] != 0:
            fails.append(f"二次 scrub 仍重写: {d['summary']}")
        if dst.read_bytes() != before:
            fails.append("二次 scrub 改了目标")

        # dry 不写
        r = run(t, "--scrub", "--json")
        if r.returncode != 0 or (t / "ssot/logs/archive-manifest.jsonl").read_text().count("\n") == 0:
            fails.append("dry scrub 失败")

        # 二进制：copy 且标记未扫描
        r = run(t, "--scrub", "--apply", "--json")
        d = json.loads(r.stdout)
        binary_rec = [x for x in d["records"] if x.get("src_path", "").endswith("c.jsonl")]
        if binary_rec and binary_rec[0].get("scrubbed"):
            fails.append("二进制不应标记 scrubbed")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   hardlink → scrub 断开，源字节不变")
    print("  ok   目标含脱敏标记、manifest sensitivity/redactions")
    print("  ok   二次 scrub 幂等")
    print("  ok   二进制 copy 且不标 scrubbed")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

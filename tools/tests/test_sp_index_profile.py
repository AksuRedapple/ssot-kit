#!/usr/bin/env python3
"""回归：sp_index 从 profile 读 batch；env 覆盖；workers 只登记不启用。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_index.py"


def status(env):
    r = subprocess.run([sys.executable, str(TOOL), "--status"], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "profile").mkdir()
        (t / "profile/embed-profile.json").write_text(
            json.dumps({"schema": 1, "client": {"batch": 128, "workers": 2}}), encoding="utf-8")
        env = dict(os.environ, SSOT_ROOT=str(t))
        rc, out = status(env)
        if rc != 0 or "batch=128(profile)" not in out:
            fails.append(f"profile batch 未生效: {out.strip()}")
        if "workers=2(profile)" not in out or "未启用" not in out:
            fails.append(f"workers 登记/提示不对: {out.strip()}")

        env2 = dict(env, SP_INDEX_BATCH="9999", SP_INDEX_WORKERS="9")
        rc, out = status(env2)
        if "batch=512(env)" not in out or "workers=8(env)" not in out:
            fails.append(f"env 覆盖/夹紧不对: {out.strip()}")

        env3 = dict(env, SP_INDEX_BATCH="bad")
        rc, out = status(env3)
        if "batch=32(env)" not in out:
            fails.append(f"非法 env 未回退默认: {out.strip()}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   profile batch=128")
    print("  ok   env 覆盖并夹紧 8..512 / 1..8")
    print("  ok   非法 env 回退默认")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

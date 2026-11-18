#!/usr/bin/env python3
"""回归：sp_index --status 检测 BUILD.model_fp 漂移并提示全量重建。"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_index.py"


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        sem = t / "S2-index/semantic"
        sem.mkdir(parents=True)
        (sem / "index.db").write_bytes(b"")
        (sem / "BUILD.json").write_text(json.dumps(
            {"chunks": 0, "model_fp": "oldmodel0000"}), encoding="utf-8")
        model = t / "m.gguf"
        model.write_bytes(b"x" * 1024)
        env = dict(os.environ, SSOT_ROOT=str(t), EMBED_MODEL=str(model))
        r = subprocess.run([sys.executable, str(TOOL), "--status"],
                           capture_output=True, text=True, env=env)
        out = r.stdout + r.stderr
        if "model : fp=" not in out:
            fails.append(f"缺 model 行: {out}")
        if "⚠ changed" not in out or "需 --full" not in out:
            fails.append(f"缺漂移提示: {out}")

        # 硬件/后端不同不应触发重建：只要 model_fp 一致
        mfp = hashlib.md5(model.read_bytes()).hexdigest()[:12]
        (sem / "BUILD.json").write_text(json.dumps(
            {"chunks": 0, "model_fp": mfp, "hardware_fp": "other-99g-darwin-99c",
             "backend": "other-backend"}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(TOOL), "--status"],
                           capture_output=True, text=True, env=env)
        out2 = r.stdout + r.stderr
        if "⚠ changed" in out2:
            fails.append(f"硬件变化误触发重建: {out2}")
        if "env   :" not in out2 or "[soft:" not in out2:
            fails.append(f"缺 soft env 行: {out2}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   model 行可见")
    print("  ok   BUILD.model_fp 不一致 → 提示 --full")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

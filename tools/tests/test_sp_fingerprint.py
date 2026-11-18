#!/usr/bin/env python3
"""回归：环境指纹字段齐全、model_fp 稳定。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        model = t / "m.gguf"
        model.write_bytes(b"x" * 1024)
        env = dict(os.environ, SSOT_ROOT=str(t), EMBED_MODEL=str(model))
        code = ("import sys,json;sys.path.insert(0,%r);import sp_fingerprint as f;"
                "print(json.dumps(f.env()))" % str(ROOT / "tools"))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            for k in ("hardware_fp", "model_fp", "llama_version", "backend"):
                if k not in d:
                    fails.append(f"缺 {k}")
            if len(d.get("model_fp", "")) != 12:
                fails.append(f"model_fp 长度不对: {d.get('model_fp')}")
            if d.get("model_path") != str(model):
                fails.append(f"model_path 不对: {d.get('model_path')}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   hardware_fp/model_fp/llama_version/backend")
    print("  ok   model_fp 12 位且跟随 EMBED_MODEL")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

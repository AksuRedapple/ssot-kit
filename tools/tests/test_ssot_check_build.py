#!/usr/bin/env python3
"""回归：ssot_check [build] 必须跟随 active 版本，不读迁移前的根 BUILD。

事故形态（2026-11-18）：--adopt 后根 BUILD.json 只是在线清单，chunks/built_at
仍是迁移前数字；[build] 直接读根清单 → 长期显示旧块数/旧时间。
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ssot_check  # noqa: E402


def mk(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def main():
    fails = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 根清单：旧读数 + 指向版本库
        mk(root, "S2-index/semantic/BUILD.json", {
            "built_at": "2026-11-12T15:29:50+08:00", "commit": "old",
            "chunks": 338176, "active": "v1", "db": "versions/v1/index.db",
        })
        vp = mk(root, "S2-index/semantic/versions/v1/BUILD.json", {
            "built_at": "2026-11-18T11:28:14+08:00", "commit": "new",
            "chunks": 349419,
        })
        got, data = ssot_check.find_build(str(root))
        if Path(got) != vp:
            fails.append(f"版本化路径未命中: {got}")
        if data.get("chunks") != 349419:
            fails.append(f"块数未跟随版本库: {data.get('chunks')}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        legacy = mk(root, "S2-index/semantic/BUILD.json", {
            "built_at": "2026-10-01T00:00:00+08:00", "commit": "legacy", "chunks": 12,
        })
        got, data = ssot_check.find_build(str(root))
        if Path(got) != legacy or data.get("chunks") != 12:
            fails.append("legacy 回退失效")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   版本化 BUILD 跟随 active")
    print("  ok   legacy 单库仍可读")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

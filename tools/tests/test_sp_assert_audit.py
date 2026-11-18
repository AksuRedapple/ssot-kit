#!/usr/bin/env python3
"""回归：sp_assert_audit 解析三种标题、重复/断号/断链/环/缺状态。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_assert_audit.py"


def main():
    fails = []
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        k = t / "knowledge"
        k.mkdir(parents=True)
        (k / "assertions.md").write_text("""
## A001 · 正常条目
- 标签：ssh ｜ 状态：现役

## A002 无分隔符条目
- 标签：x ｜ 状态：已过时
superseded_by: A003

## A003 — 短横线条目
- 标签：y ｜ 状态：现役

## A003 · 重复编号
- 状态：现役

## A005 · 环一
- 状态：现役
superseded_by: A006

## A006 · 环二
- 状态：现役
superseded_by: A005

## A007 · 缺状态
- 标签：z

## A008 · 断链
- 状态：已过时
superseded_by: A999
""", encoding="utf-8")
        (t / "lines").mkdir()
        (t / "lines/demo.md").write_text("见 A001 和 A003\n", encoding="utf-8")
        env = dict(os.environ, SSOT_ROOT=str(t))
        r = subprocess.run([sys.executable, str(TOOL), "--json"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            fails.append(f"rc={r.returncode}: {r.stderr}")
        else:
            d = json.loads(r.stdout)
            if d["total"] != 8:
                fails.append(f"total 不对: {d['total']}")
            if d["dups"] != ["A003"]:
                fails.append(f"dups 不对: {d['dups']}")
            if "A004" not in d["gaps"]:
                fails.append(f"gaps 不对: {d['gaps']}")
            if "A007" not in d["missing_status"]:
                fails.append(f"missing_status 不对: {d['missing_status']}")
            if d["broken_refs"] != ["A008"]:
                fails.append(f"broken 不对: {d['broken_refs']}")
            if not d["cycles"]:
                fails.append(f"cycles 未检出: {d['cycles']}")
            if d["citations"]["cited_assertions"] < 2:
                fails.append(f"citations 不对: {d['citations']}")
        r = subprocess.run([sys.executable, str(TOOL), "--strict"],
                           capture_output=True, text=True, env=env)
        if r.returncode != 1:
            fails.append(f"--strict 应 rc=1，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   三种标题 + 重复/断号/缺状态")
    print("  ok   断链/环/引用")
    print("  ok   --strict rc=1")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""回归：sid_from_path 存在且口径正确（2026-11-19 NameError 事故）。

事故现场：main() 调 sid_from_path() 但函数从未定义 → 语义检索全线下线。
判据用 2026-11-19T01:47 的真实 search-log 反推：目录名日期后的 8 位 hex。
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
if importlib.util.find_spec("numpy") is None:
    print("skip: numpy not installed（读路径需要；写路径仍应可测）")
    sys.exit(77)   # 77 = SKIP（run_all 协议；0 会被当成 PASS，见 A562）
import sp_semantic  # noqa: E402

# 历史日志（S2-index/search-log.jsonl @ 2026-11-19T01:47:31）里的原样路径
CASES = [
    ("evidence/qoder/S1-sessions/2026-11-04-22ed5f66-我本地-qoder-有好多-ss-怎么手机上看不到/transcript.jsonl",
     "22ed5f66"),
    ("evidence/cc/S1-subagents/2026-09-15-0c97ee41-我现在要给你两段文字-你先接着/agent-ab76df7055a7cac77.jsonl",
     "0c97ee41"),
    ("evidence/qoder/S1-sessions/2026-11-03-b9dc055a-读-x/transcript.jsonl", "b9dc055a"),
    ("evidence/cc/S1-subagents/2026-09-15-0c97ee41-我再讲一段/subagents.md", "0c97ee41"),
    # 非会话块必须为空（不能把正本/线页/收件箱算成会话）
    ("knowledge/assertions.md", ""),
    ("lines/network-domain.md", ""),
    ("inbox/2026-11-19.md", ""),
    ("", ""),
]


def main():
    fails = []

    f = getattr(sp_semantic, "sid_from_path", None)
    if not callable(f):
        print("  FAIL sid_from_path 未定义（事故回归）")
        print("有失败")
        return 1
    print("  ok   sid_from_path 已定义")

    for path, want in CASES:
        got = f(path)
        if got != want:
            fails.append(f"{path or '<empty>'} → {got!r}（期望 {want!r}）")
    if not fails:
        print("  ok   历史样本口径（22ed5f66 / 0c97ee41）")
        print("  ok   非会话块不误判")

    # 真实库全量路径：会话块必须都能解析，非会话块必须一个都不解析
    db = Path(sp_semantic.DB)
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        paths = [r[0] for r in con.execute("select distinct path from chunks")]
        con.close()
        s1 = [p for p in paths if "/S1-sessions/" in p or "/S1-subagents/" in p]
        miss = [p for p in s1 if not f(p)]
        false_pos = [p for p in paths if p not in set(s1) and f(p)]
        if miss:
            fails.append(f"{len(miss)} 条会话路径解析不出 sid，例：{miss[:3]}")
        if false_pos:
            fails.append(f"{len(false_pos)} 条非会话路径被误判，例：{false_pos[:3]}")
        print(f"  ok   真实库 {len(s1)} 条会话路径全解析 / {len(paths) - len(s1)} 条非会话零误判")
    else:
        print("  skip 真实库不存在，只跑样本")

    if fails:
        for x in fails:
            print("  FAIL", x)
        print("有失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

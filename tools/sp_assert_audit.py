#!/usr/bin/env python3
"""sp_assert_audit · 断言库体检（P2 phase 0，只读）

回答四个问题：
  1) 552 条断言的状态/标签/取代关系是否完整；
  2) 有没有重复编号、断号、superseded_by 断链、环、自指；
  3) 现在按 700/1400 字切块，有多少块跨多条断言、多少断言被切开；
  4) 改成“一条断言一块”大概多少块、多少超长、重建成本。

用法:
  python3 tools/sp_assert_audit.py
  python3 tools/sp_assert_audit.py --json
  python3 tools/sp_assert_audit.py --strict     # 有硬问题则 rc=1
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib.index.chunking import chunk_file  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
ASSERT = os.path.join(SSOT, 'knowledge', 'assertions.md')
from ssotlib.asserts import CITE_RX, parse  # noqa: E402


def citations(ids):
    roots = [os.path.join(SSOT, 'lines'), os.path.join(SSOT, 'knowledge'),
             os.path.join(SSOT, 'inbox')]
    pages = {}
    for root in roots:
        for p in glob.glob(os.path.join(root, '**', '*.md'), recursive=True):
            if os.path.abspath(p) == os.path.abspath(ASSERT):
                continue
            try:
                text = open(p, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            found = set(CITE_RX.findall(text)) & ids
            for a in found:
                pages.setdefault(a, set()).add(os.path.relpath(p, SSOT))
    return pages


def cycles(blocks):
    m = {b['id']: b['superseded_by'] for b in blocks if b['superseded_by']}
    out = set()
    for start in m:
        seen, cur = [], start
        while cur in m:
            if cur in seen:
                out.add('→'.join(seen[seen.index(cur):] + [cur]))
                break
            seen.append(cur)
            cur = m[cur]
    return sorted(out)


def chunk_stats(blocks):
    try:
        chunks = chunk_file(ASSERT)
    except Exception:
        chunks = []
    multi = zero = split = 0
    for i, (start, text, *_rest) in enumerate(chunks):
        n = len(re.findall(r'(?m)^##\s*A\d+', text))
        if n >= 2:
            multi += 1
        elif n == 0:
            zero += 1
    starts = [c[0] for c in chunks] + [10 ** 9]
    for b in blocks:
        if any(b['line'] < s <= b['end'] for s in starts[1:]):
            split += 1
    long_blocks = [b for b in blocks if b['chars'] > 1400]
    return {
        'current_chunks': len(chunks),
        'chunks_with_multi_assertion': multi,
        'chunks_with_zero_heading': zero,
        'assertions_split_across_chunks': split,
        'assertion_level_chunks': len(blocks),
        'long_assertions_gt_1400': len(long_blocks),
        'max_assertion_chars': max([b['chars'] for b in blocks] or [0]),
        'total_assertion_chars': sum(b['chars'] for b in blocks),
    }


def audit():
    blocks = parse(ASSERT)
    ids = {b['id'] for b in blocks}
    dups = sorted({b['id'] for b in blocks if sum(1 for x in blocks if x['id'] == b['id']) > 1})
    nums = sorted(int(re.match(r'A(\d+)', b['id']).group(1)) for b in blocks)
    gaps = [f'A{n:03d}' for n in range(1, (max(nums) if nums else 0) + 1) if n not in nums]
    missing_status = [b['id'] for b in blocks if not b.get('status_raw')]
    sup_missing = [b['id'] for b in blocks if b['status'] == 'superseded'
                   and not b['superseded_by']]
    broken = [b['id'] for b in blocks if b['superseded_by'] and b['superseded_by'] not in ids]
    cyc = cycles(blocks)
    cit = citations(ids)
    cited = sum(1 for b in blocks if b['id'] in cit)
    return {
        'total': len(blocks),
        'ids': sorted(ids),
        'status_counts': {s: sum(1 for b in blocks if b['status'] == s)
                          for s in sorted({b['status'] for b in blocks})},
        'dups': dups,
        'gaps': gaps,
        'missing_status': missing_status,
        'superseded_missing_target': sup_missing,
        'broken_refs': broken,
        'cycles': cyc,
        'citations': {'cited_assertions': cited, 'uncited': len(blocks) - cited,
                      'top': sorted(((a, len(p)) for a, p in cit.items()),
                                    key=lambda x: -x[1])[:10]},
        'chunking': chunk_stats(blocks),
    }


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_assert_audit.py\n  sp_assert_audit.py --json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args()
    d = audit()
    hard = bool(d['dups'] or d['broken_refs'] or d['cycles'] or d['superseded_missing_target'])
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print(f"断言：{d['total']} 条")
        print("状态：" + ' / '.join(f"{k or '<空>'} {v}" for k, v in d['status_counts'].items()))
        print(f"重复编号：{len(d['dups'])}" + (f" {d['dups']}" if d['dups'] else ''))
        print(f"断号：{len(d['gaps'])}" + (f" {d['gaps'][:10]}" if d['gaps'] else ''))
        print(f"缺 status：{len(d['missing_status'])}" + (f" {d['missing_status'][:10]}" if d['missing_status'] else ''))
        print(f"已过时但无 superseded_by：{len(d['superseded_missing_target'])}"
              + (f" {d['superseded_missing_target'][:10]}" if d['superseded_missing_target'] else ''))
        print(f"superseded_by 断链：{len(d['broken_refs'])}" + (f" {d['broken_refs']}" if d['broken_refs'] else ''))
        print(f"取代环：{len(d['cycles'])}" + (f" {d['cycles'][:3]}" if d['cycles'] else ''))
        c = d['chunking']
        print(f"引用：{d['citations']['cited_assertions']} 条被引用 / {d['citations']['uncited']} 条零引用"
              + (f"；top {d['citations']['top'][:5]}" if d['citations']['top'] else ''))
        print(f"切块：当前 {c['current_chunks']} 块 · 跨多条 {c['chunks_with_multi_assertion']} · "
              f"无标题 {c['chunks_with_zero_heading']} · 断言被切开 {c['assertions_split_across_chunks']}")
        print(f"断言级：{c['assertion_level_chunks']} 块 · 超 1400 字 {c['long_assertions_gt_1400']} · "
              f"最长 {c['max_assertion_chars']} 字")
    if a.strict and hard:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

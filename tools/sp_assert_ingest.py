#!/usr/bin/env python3
"""sp_assert_ingest · 把蒸馏草稿里的断言并入正本(编号 + 撞正本 + 格式化)

用法:
  python3 tools/sp_assert_ingest.py --dir compile/llm-distill-batch --dry-run
  python3 tools/sp_assert_ingest.py --dir compile/llm-distill-batch --apply
"""
import argparse, glob, importlib.util, json, os, re, sys

SSOT = os.path.expanduser('~/ssot')
ASSERT = os.path.join(SSOT, 'knowledge', 'assertions.md')
THR_DUP = 0.88


def drafts(dirpath):
    out = []
    for f in sorted(glob.glob(os.path.join(SSOT, dirpath, '*.md'))):
        name = os.path.basename(f)
        if name.startswith('REVIEW') or name == 'ADOPTION.md':
            continue
        for ln in open(f, encoding='utf-8'):
            m = re.match(r'- \[(\w+)\] (.+?)\s*｜tags:\s*(.*)$', ln.strip())
            if m:
                out.append({'type': m.group(1), 'claim': m.group(2).strip(),
                            'tags': [t.strip() for t in m.group(3).split(',') if t.strip()],
                            'src': dirpath + '/' + name})
    return out


def existing():
    items = []
    for block in re.split(r'\n## ', open(ASSERT, encoding='utf-8').read()):
        m = re.match(r'(A\d{3})', block)
        if not m:
            continue
        title = block.split('\n')[0][6:].strip()
        body = re.sub(r'\s+', ' ', block)[:400]
        items.append((m.group(1), title, body))
    return items


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_assert_ingest.py --dir compile/llm-distill-batch --dry-run',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', required=True)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--thr', type=float, default=THR_DUP)
    a = ap.parse_args()

    ds = drafts(a.dir)
    if not ds:
        print('未找到断言草稿'); return 1
    ex = existing()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_assert_alloc import alloc, commit
    ids = alloc(len(keep)) if keep else []
    last = None
    spec = importlib.util.spec_from_file_location('sem', os.path.join(SSOT, 'tools', 'sp_semantic.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    import numpy as np
    E = np.array([np.asarray(m.embed(m.QUERY_PREFIX + t + ' ' + b), dtype=np.float32) for _, t, b in ex])
    E /= (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    keep, dup = [], []
    for d in ds:
        v = np.asarray(m.embed(m.QUERY_PREFIX + d['claim']), dtype=np.float32)
        v /= (np.linalg.norm(v) + 1e-9)
        s = float((E @ v).max())
        d['sim'] = round(s, 3)
        (dup if s >= a.thr else keep).append(d)
    print(f'草稿断言 {len(ds)} · 撞正本(≥{a.thr}) {len(dup)} · 待入册 {len(keep)}')
    for d in dup[:8]:
        print(f"  ⊘ [{d['sim']}] {d['claim'][:46]}")
    if not a.apply:
        for i, d in enumerate(keep, 1):
            print(f"  + A{ids[i-1]} [{d['type']}] {d['claim'][:52]}")
        print('\n[dry-run] 未写入;--apply 才落正本')
        return 0
    lines = []
    for i, d in enumerate(keep, 1):
        num = f'A{ids[i-1]}'
        title = d['claim'][:34].rstrip('，。')
        lines.append(f"\n## {num} — {title}\n"
                     f"**事实（2026-11-01，LLM 蒸馏 · {os.path.basename(d['src']).replace('.md','')}）**：{d['claim']}\n"
                     f"**判据/处方**：按此条执行；与实测冲突时以实测为准并回写本条。\n"
                     f"**来源**：`{d['src']}` ｜ 标签：{','.join(d['tags']) or '蒸馏'} ｜ 状态：现役\n")
    with open(ASSERT, 'a', encoding='utf-8') as f:
        f.write(''.join(lines))
    commit(ids)
    print(f'已写入 {len(keep)} 条(A{ids[0]}–A{ids[-1]})')
    json.dump({'added': len(keep), 'dup': len(dup), 'first': f'A{ids[0]}', 'last': f'A{ids[-1]}'},
              open(os.path.join(SSOT, a.dir, 'ASSERTIONS-INGEST.json'), 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

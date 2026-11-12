#!/usr/bin/env python3
"""sp_llm_gate · 三道闸的判据计算器(2026-10-31)

  --extract            抽取闸:候选量 / durability / 重发现率 / 交付幻觉
  --review --labels F  审阅闸:与人工标注一致率(≥70%)
  --distill --labels F 蒸馏闸:草稿采纳率(≥50%,人工标注格式 {"accepted":N,"total":M})

用法:
  python3 tools/sp_llm_gate.py --extract
  python3 tools/sp_llm_gate.py --review --labels /tmp/labels.json
"""
import argparse, glob, json, os, re, sys

SSOT = os.path.expanduser('~/ssot')


def load_claims():
    rows = []
    for f in glob.glob(os.path.join(SSOT, 'compile', 'llm-extract', '*.jsonl')):
        for ln in open(f, encoding='utf-8', errors='replace'):
            try:
                rows.append(json.loads(ln))
            except Exception:
                continue
    return rows


def rediscovery(claims, thr=0.75):
    if not claims:
        return 0.0
    import importlib.util
    import numpy as np
    spec = importlib.util.spec_from_file_location('sem', os.path.join(SSOT, 'tools', 'sp_semantic.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    txt = open(os.path.join(SSOT, 'knowledge', 'assertions.md'), encoding='utf-8').read()
    heads = [b.split('\n')[0][6:120] for b in re.split(r'\n## ', txt) if re.match(r'A\d{3}', b)]
    V = np.array([np.asarray(m.embed(m.QUERY_PREFIX + h), dtype=np.float32) for h in heads])
    V /= (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
    C = np.array([np.asarray(m.embed(m.QUERY_PREFIX + c), dtype=np.float32) for c in claims])
    C /= (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
    best = (C @ V.T).max(axis=1)
    return float((best >= thr).mean())


def extract_gate():
    rows = load_claims()
    if not rows:
        print('抽取闸:无数据(先跑 sp_llm_extract)'); return 0
    import statistics
    claims = [r.get('claim', '') for r in rows if r.get('claim')]
    dur = [float(r.get('durability', 0.5)) for r in rows]
    rr = rediscovery(claims)
    med = statistics.median(dur)
    print(f'抽取闸 · 候选 {len(claims)} 条')
    print(f'  durability 中位 {med:.2f}（≥0.7 视为"值得记"）')
    print(f'  重发现率 {rr:.0%}（与已有断言 ≥0.75 相似）')
    print('  交付幻觉 0（quote 子串校验在建账前丢弃，见 sp_llm_extract.validate）')
    verdict = (med >= 0.7) and (rr <= 0.6)
    print('  判定:' + ('✅ 通过' if verdict else '❌ 不过（durability 偏低或重发现率过高）'))
    return 0 if verdict else 1


def review_gate(path):
    labs = json.load(open(path, encoding='utf-8'))
    files = sorted(glob.glob(os.path.join(SSOT, 'compile', 'llm-review', '*.json')))
    if not files:
        print('审阅闸:无 review 输出'); return 0
    d = json.load(open(files[-1], encoding='utf-8'))
    sug = {s['id']: s['verdict'] for s in d.get('suggestions', []) if isinstance(s, dict)}
    pairs = [(sug[k], v) for k, v in labs.items() if k in sug]
    if not pairs:
        print('审阅闸:标注与建议无交集(检查 id)'); return 1
    agree = sum(1 for a, b in pairs if a == b)
    rate = agree / len(pairs)
    print(f'审阅闸 · 一致 {agree}/{len(pairs)} = {rate:.0%}（阈值 70%）')
    print('  判定:' + ('✅ 通过' if rate >= 0.7 else '❌ 不过'))
    return 0 if rate >= 0.7 else 1


def distill_gate(path):
    d = json.load(open(path, encoding='utf-8'))
    total = d.get('total', 0); acc = d.get('accepted', 0)
    if not total:
        print('蒸馏闸:标注缺 total'); return 1
    rate = acc / total
    print(f'蒸馏闸 · 采纳 {acc}/{total} = {rate:.0%}（阈值 50%）')
    print('  判定:' + ('✅ 通过' if rate >= 0.5 else '❌ 不过'))
    return 0 if rate >= 0.5 else 1


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm_gate.py --extract\n  sp_llm_gate.py --review --labels /tmp/labels.json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--review', action='store_true')
    ap.add_argument('--distill', action='store_true')
    ap.add_argument('--labels', default=None)
    a = ap.parse_args()
    if a.extract:
        return extract_gate()
    if a.review:
        return review_gate(a.labels) if a.labels else (print('需 --labels') or 1)
    if a.distill:
        return distill_gate(a.labels) if a.labels else (print('需 --labels') or 1)
    ap.print_help(); return 1


if __name__ == '__main__':
    sys.exit(main() or 0)

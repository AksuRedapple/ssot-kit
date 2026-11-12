#!/usr/bin/env python3
"""sp_llm_review · 审阅助手:账本候选 → A/R 建议 + 理由(不落盘、不改账本)

设计:§4.6 第 2 级。判 A=值得进正本;R=过程性/重复/无出处价值。
输出 compile/llm-review/<date>.json,供人一键采纳。

用法:
  python3 tools/sp_llm_review.py --limit 12 [--batch 12] [--dry-run]
  ZB_LLM_MOCK=1 python3 tools/sp_llm_review.py --limit 2
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sp_llm import run_llm

SSOT = os.path.expanduser('~/ssot')
LEDGER = os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')
SCHEMA = os.path.join(SSOT, 'schemas', 'review.json')
OUT = os.path.join(SSOT, 'compile', 'llm-review')

PROMPT = '''你是知识审阅员。下面是候选条目(来自真实会话抽取)。逐条判 A 或 R。

判 A(值得进正本):三个月后仍有用;是判断/口径/教训/决定,不是过程叙述。
判 R(拒绝):过程性叙述、临时状态、重复已知、只对当次有效、无信息量。

判据细节:
- 有具体数字/版本/路径/阈值的,优先 A
- "我打算/下一步要/正在做" → R(过程)
- "已确认/已修复/根因是" → A
- 只描述某次操作步骤、不含可复用结论 → R

候选:
{cands}

只输出 JSON:{{"suggestions":[{{"id":"...","verdict":"A|R","reason":"≤30字"}}]}}'''

CARD_TOP = 12


def load_candidates(limit=12, state='candidate'):
    rows = []
    if not os.path.exists(LEDGER):
        return rows
    for ln in open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            c = json.loads(ln)
        except Exception:
            continue
        if c.get('state') != state:
            continue
        ev = (c.get('evidence') or [{}])[0]
        rows.append({'id': c['id'], 'claim': c.get('claim', '')[:160], 'type': c.get('type'),
                     'quote': (ev.get('quote') or '')[:160], 'source': ev.get('session', '')})
        if len(rows) >= limit:
            break
    return rows


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm_review.py --limit 12\n  sp_llm_review.py --limit 12 --dry-run',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--limit', type=int, default=12)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    cands = load_candidates(a.limit)
    if not cands:
        print('账本里没有 candidate 状态条目'); return 0
    body = '\n'.join(f"- id={c['id']} [{c['type']}] {c['claim']}  (quote: {c['quote'][:60]})" for c in cands)
    prompt = PROMPT.replace('{cands}', body)
    if a.dry_run:
        print(prompt[:1200]); return 0
    try:
        data = run_llm(prompt, SCHEMA, tag=f'review:{len(cands)}')
    except Exception as e:  # noqa: BLE001
        print(f'❌ {e}'); return 1
    sug = data.get('suggestions') if isinstance(data, dict) else data
    if not isinstance(sug, list):
        sug = []
    byid = {s['id']: s for s in sug if isinstance(s, dict) and s.get('id')}
    nA = sum(1 for s in byid.values() if s.get('verdict') == 'A')
    print(f'候选 {len(cands)} 条 → 建议 A {nA} / R {len(byid) - nA}')
    for c in cands:
        s = byid.get(c['id'])
        if s:
            print(f"  {s['verdict']} {c['claim'][:52]:52s} | {s['reason'][:26]}")
        else:
            print(f"  ? {c['claim'][:52]:52s} | (模型未返回)")
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, __import__('time').strftime('%Y-%m-%d-%H%M') + '.json')
    json.dump({'ts': __import__('time').strftime('%F %T'), 'n': len(cands),
               'suggestions': sug, 'candidates': cands}, open(dst, 'w'), ensure_ascii=False, indent=1)
    print(f'→ {os.path.relpath(dst, SSOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

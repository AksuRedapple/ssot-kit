#!/usr/bin/env python3
"""sp_llm_distill · 蒸馏助手:一批候选/贡献 → 线页段落草稿 + 断言草稿(人审后落正本)

设计:§4.6 第 3 级。**只产草稿**,写 compile/llm-distill/<date>.md,永不写 lines/ 或 assertions.md。

用法:
  python3 tools/sp_llm_distill.py --from-extract <sid8>          # 用某会话的抽取结果
  python3 tools/sp_llm_distill.py --from-ledger --limit 12       # 用账本里 A 状态的条目
  ZB_LLM_MOCK=1 python3 tools/sp_llm_distill.py --from-extract x
"""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sp_llm import run_llm

SSOT = os.path.expanduser('~/ssot')
SCHEMA = os.path.join(SSOT, 'schemas', 'distill.json')
OUT = os.path.join(SSOT, 'compile', 'llm-distill')
LEDGER = os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')

PROMPT = '''你是知识编辑。把下面这批候选,压缩成两类草稿:

1) line_sections:1–3 个小节,每节 2–6 条 bullet,给工作线页用。要具体(带数字/路径),不要空话。
2) assertions:0–4 条可复用断言,每条一句成文法,必须能脱离上下文读懂。

规则:
- 同义合并;隐私/凭据/公司名一律不写
- 没有达到"可复用"的,宁可返回空数组
- 不要编造候选里没有的信息

候选:
{cands}

只输出 JSON 对象:{{"line_sections":[{{"title":"...","bullets":["..."]}}],"assertions":[{{"claim":"...","type":"fact|decision|insight|correction","tags":["..."]}}]}}'''


def from_extract(sid):
    f = os.path.join(SSOT, 'compile', 'llm-extract', f'{sid}.jsonl')
    if not os.path.exists(f):
        return []
    out = []
    for ln in open(f, encoding='utf-8'):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        out.append(d)
    return out


def from_ledger(limit):
    out = []
    for ln in open(LEDGER, encoding='utf-8', errors='replace'):
        try:
            c = json.loads(ln)
        except Exception:
            continue
        if c.get('state') in ('accepted', 'candidate'):
            out.append({'claim': c.get('claim'), 'type': c.get('type'),
                        'quote': ((c.get('evidence') or [{}])[0].get('quote') or '')})
        if len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm_distill.py --from-extract b0a82327\n  sp_llm_distill.py --from-ledger --limit 12',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from-extract')
    ap.add_argument('--from-ledger', action='store_true')
    ap.add_argument('--limit', type=int, default=12)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    items = from_extract(a.from_extract) if a.from_extract else (from_ledger(a.limit) if a.from_ledger else [])
    if not items:
        print('没有输入(先跑 sp_llm_extract 或指定 --from-ledger)'); return 0
    body = '\n'.join(f"- [{i.get('type','?')}] {i.get('claim','')}" for i in items)
    prompt = PROMPT.replace('{cands}', body)
    if a.dry_run:
        print(prompt[:900]); return 0
    try:
        data = run_llm(prompt, SCHEMA, tag=f'distill:{len(items)}')
    except Exception as e:  # noqa: BLE001
        print(f'❌ {e}'); return 1
    secs = data.get('line_sections') or []
    asserts = data.get('assertions') or []
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, __import__('time').strftime('%Y-%m-%d-%H%M') + '.md')
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(f"# 蒸馏草稿 · {__import__('time').strftime('%F %H:%M')}（**未入正本,待人审**）\n\n")
        f.write(f"> 输入 {len(items)} 条候选;来源 {'extract:' + a.from_extract if a.from_extract else 'ledger'}\n\n")
        for s in secs:
            f.write(f"## {s.get('title','(无标题)')}\n")
            for b in s.get('bullets', []):
                f.write(f"- {b}\n")
            f.write('\n')
        if asserts:
            f.write('## 断言草稿（未编号）\n')
            for x in asserts:
                f.write(f"- [{x.get('type')}] {x.get('claim')}  ｜tags: {', '.join(x.get('tags', []))}\n")
    print(f'段落 {len(secs)} / 断言草稿 {len(asserts)} → {os.path.relpath(dst, SSOT)}')
    for s in secs:
        print(f"  ## {s.get('title','')[:40]} ({len(s.get('bullets', []))} 条)")
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

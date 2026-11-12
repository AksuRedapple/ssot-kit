#!/usr/bin/env python3
"""sp_llm_extract · LLM 抽取:原始对话分块 → 候选 JSON(quote 必须在原文中)

设计:§4.6 第 1 级。只产候选,写 compile/llm-extract/<sid>.jsonl,不碰账本/正本。

用法:
  python3 tools/sp_llm_extract.py --sid 4a4753ed [--chunk 200] [--max-chunks 3] [--dry-run]
  ZB_LLM_MOCK=1 ZB_LLM_MOCK_JSON='{...}' python3 tools/sp_llm_extract.py --sid X   # 测试
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sp_llm import run_llm, PROMPT_VER

SSOT = os.path.expanduser('~/ssot')
OUT = os.path.join(SSOT, 'compile', 'llm-extract')
SCHEMA = os.path.join(SSOT, 'schemas', 'candidate.json')
CARD_CACHE = os.path.join(SSOT, 'logs', 'context-card.md')

PROMPT = '''你是知识抽取器。下面是一段**真实的人机对话**(带行号),请抽出**值得长期记住**的内容。

判据(宁缺勿滥,没有就返回空数组):
- 只抽:①坐实的事实(带数字/版本/路径/结论)②做过的决定(含理由)③反直觉的教训④明确的未尽事项
- 不抽:寒暄、过程性叙述、工具原始输出、重复的解释、只对当次有效的临时状态
- claim 用≤50字的一句话概括,必须能脱离上下文读懂
- quote 必须是原文中**逐字存在**的片段(20-120字),不许改写
- line 是该片段所在的行号
- durability: 三个月后还有用=0.8+,只对当次有用=0.2以下
- why: ≤30字,说明为什么值得记

以下是本库已有的知识结构(用来判断"什么算值得记"),不要把它当输入:
---
{card}
---

对话分块(第 {start}-{end} 行):
{body}

只输出 JSON,严格符合 schema:顶层必须是对象 {"candidates": [...]}。
'''


def build_card():
    if os.path.exists(CARD_CACHE) and time_fresh(CARD_CACHE):
        return open(CARD_CACHE, encoding='utf-8').read()
    parts = []
    lines_dir = os.path.join(SSOT, 'lines')
    titles = []
    for f in sorted(glob.glob(lines_dir + '/*.md')):
        if os.path.basename(f).startswith('_'):
            continue
        for ln in open(f, encoding='utf-8', errors='replace'):
            if ln.startswith('# '):
                titles.append(ln[2:].strip())
                break
    parts.append('工作线:' + ' / '.join(titles[:18]))
    ol = os.path.join(SSOT, 'knowledge', 'open-loops.md')
    if os.path.exists(ol):
        act = [l.strip()[2:60] for l in open(ol, encoding='utf-8', errors='replace') if l.startswith('- 🎯')]
        parts.append('在推事项:' + ' | '.join(act[:4]))
    ap = os.path.join(SSOT, 'knowledge', 'assertions.md')
    if os.path.exists(ap):
        heads = [l[3:].strip()[:48] for l in open(ap, encoding='utf-8', errors='replace') if l.startswith('## A')][-12:]
        parts.append('近期断言样例:' + ' | '.join(heads))
    card = '\n'.join(parts)
    os.makedirs(os.path.dirname(CARD_CACHE), exist_ok=True)
    open(CARD_CACHE, 'w', encoding='utf-8').write(card)
    return card


def time_fresh(p, days=1):
    import time
    return (time.time() - os.path.getmtime(p)) < days * 86400


def find_transcript(sid):
    for f in glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', f'*{sid}*', 'transcript.jsonl')):
        return f
    return None


def rows_with_lines(path):
    out = []
    for i, ln in enumerate(open(path, encoding='utf-8', errors='replace'), 1):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        txt = r.get('content')
        if not isinstance(txt, str) or not txt.strip():
            continue
        out.append((i, r.get('role', '?'), txt))
    return out


def normalize(s):
    return re.sub(r'\s+', '', s)


def validate(cands, chunk_text):
    """quote 必须逐字存在于本块;line 必须在块内;claim 非空。返回(保留, 丢弃理由)"""
    keep, drop = [], []
    nt = normalize(chunk_text)
    for c in cands:
        q = c.get('quote') or ''
        if len(q) < 8:
            drop.append(('quote 过短', c)); continue
        if normalize(q) not in nt:
            drop.append(('quote 不在原文', c)); continue
        if not (c.get('claim') or '').strip():
            drop.append(('claim 为空', c)); continue
        if c.get('type') not in ('fact', 'decision', 'insight', 'open-loop', 'correction'):
            c['type'] = 'fact'
        try:
            c['durability'] = max(0.0, min(1.0, float(c.get('durability', 0.5))))
        except (TypeError, ValueError):
            c['durability'] = 0.5
        c['claim'] = (c.get('claim') or '').strip()[:80]
        c['why'] = (c.get('why') or '')[:60]
        keep.append(c)
    return keep, drop


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm_extract.py --sid 4a4753ed --max-chunks 2 --dry-run\n  sp_llm_extract.py --sid 4a4753ed',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sid', required=True)
    ap.add_argument('--chunk', type=int, default=200)
    ap.add_argument('--max-chunks', type=int, default=0)
    ap.add_argument('--model', default=None)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--to-ledger', action='store_true', help='把候选写进账本(默认只写 compile/)')
    ap.add_argument('--force', action='store_true', help='忽略已完成的块,重跑全部')
    ap.add_argument('--sample', type=int, default=0, help='等距取 N 块(公平基线用)')
    ap.add_argument('--out', default=None, help='输出文件(默认 compile/llm-extract/<sid>.jsonl)')
    ap.add_argument('--ranges', default=None, help='指定行段(如 10-200,3000-3200),用于定向抽取')
    ap.add_argument('--stop-ratio', type=float, default=0.0, help='因果自适应停止:上一块产量 < 该比例×前两块均值 则停(0=关)')
    a = ap.parse_args()

    tx = find_transcript(a.sid)
    if not tx:
        print(f'❌ 找不到会话 {a.sid} 的 transcript'); return 1
    rows = rows_with_lines(tx)
    if not rows:
        print('会话为空'); return 0
    card = build_card()
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.abspath(a.out) if a.out else os.path.join(OUT, f'{a.sid}.jsonl')
    chunk_log = dst + '.chunks'          # 与输出文件绑定:--out 时状态也隔离
    total_log = dst + '.total'
    if a.out:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    if a.ranges:
        spans = []
        for part in a.ranges.split(','):
            lo, hi = (part.split('-') + [part])[:2]
            spans.append((int(lo), int(hi)))
        chunks = [[r for r in rows if lo <= r[0] <= hi] for lo, hi in spans]
        chunks = [c for c in chunks if c]
    else:
        chunks = [rows[i:i + a.chunk] for i in range(0, len(rows), a.chunk)]
    if a.sample and len(chunks) > a.sample:
        n = len(chunks)
        picks = sorted({round(i * (n - 1) / (a.sample - 1)) for i in range(a.sample)}) if a.sample > 1 else [0]
        chunks = [chunks[i] for i in picks]
    if a.max_chunks:
        chunks = chunks[:a.max_chunks]
    open(total_log, 'w', encoding='utf-8').write(str(len(chunks)))   # 计划块数(供完成判定)

    done_chunks = set()
    if os.path.exists(chunk_log) and not a.force:
        done_chunks = {int(x) for x in open(chunk_log, encoding='utf-8').read().split() if x.strip().isdigit()}
    if os.path.exists(dst) and not a.force:      # 兼容:老文件里没有 chunk 日志
        for ln in open(dst, encoding='utf-8', errors='replace'):
            try:
                done_chunks.add(json.loads(ln).get('chunk'))
            except Exception:
                pass
    total_keep = total_drop = 0
    yields = []
    with open(dst, 'a', encoding='utf-8') as fh:
        for ci, ch in enumerate(chunks, 1):
            if ci in done_chunks:
                continue
            start, end = ch[0][0], ch[-1][0]
            parts, used = [], 0
            for ln, role, txt in ch:                      # 控制单次 prompt 体积(长会话会爆)
                piece = f'[{ln}][{role}] {txt[:600]}'
                if used + len(piece) > 45000:
                    parts.append('…(本块过长,余下内容截断)')
                    break
                parts.append(piece); used += len(piece)
            body = '\n'.join(parts)
            prompt = (PROMPT.replace('{card}', card).replace('{start}', str(start))
                      .replace('{end}', str(end)).replace('{body}', body))
            if a.dry_run:
                print(f'--- chunk {ci} L{start}-{end} prompt={len(prompt)} 字符 ---')
                print(prompt[:600]); continue
            try:
                data = run_llm(prompt, SCHEMA, model=a.model, tag=f'extract:{a.sid}:{ci}')
            except Exception as e:  # noqa: BLE001
                print(f'  chunk {ci} 失败: {e}'); continue
            cands = data.get('candidates') if isinstance(data, dict) else data
            if not isinstance(cands, list):
                cands = []
            if a.stop_ratio and len(yields) >= 3:
                ref = sum(yields[:2]) / 2.0
                if yields[-1] < a.stop_ratio * ref:
                    print(f'  ⏹ 自适应停止:L{start} 之前一块产量 {yields[-1]} < {a.stop_ratio}×前两块均值 {ref:.1f}')
                    break
            keep, drop = validate(cands, body)
            yields.append(len(keep))
            total_keep += len(keep); total_drop += len(drop)
            for c in keep:
                c.update({'sid': a.sid, 'src_path': os.path.relpath(tx, SSOT),
                          'chunk': ci, 'prompt_ver': PROMPT_VER})
                fh.write(json.dumps(c, ensure_ascii=False) + '\n')
            fh.flush()                      # 逐块落盘:中断不丢已完成块
            with open(chunk_log, 'a', encoding='utf-8') as cf:
                cf.write(f'{ci}\n')          # 即使 0 条候选,也记录"这块跑过了'
            print(f'  chunk {ci} L{start}-{end}: 保留 {len(keep)} / 丢弃 {len(drop)}'
                  + (f'  例:{keep[0]["claim"][:30]}' if keep else ''))
            for why, c in drop:
                print(f'    ✗ {why}: {(c.get("quote") or "")[:40]}')
    if not a.dry_run:
        print(f'候选 {total_keep} 条(丢弃 {total_drop}) → {os.path.relpath(dst, SSOT)}')
        if a.to_ledger and total_keep:
            ingest_to_ledger(dst)
    return 0


def ingest_to_ledger(jsonl_path):
    """候选 → 账本:写 cand.v1 staging → sp_candidates --ingest → 撞正本分类"""
    import hashlib, re as _re, subprocess
    rows = []
    for ln in open(jsonl_path, encoding='utf-8'):
        try:
            c = json.loads(ln)
        except Exception:
            continue
        key = hashlib.sha1(_re.sub(r'\d+', '<n>', c.get('claim', '')).encode()).hexdigest()
        rows.append({'schema': 'cand.v1', 'id': 'cand_llm_' + key[:16], 'type': c.get('type', 'fact'),
                     'claim': c.get('claim', ''), 'quote': c.get('quote', ''),
                     'source': f"session:{c.get('sid','')}#{c.get('sid','')}@L{c.get('line',1)}",
                     'quote_sha1': hashlib.sha1((c.get('quote') or '').encode()).hexdigest(),
                     'origin': 'llm:v1', 'capture_reason': 'llm_extract',
                     'owner': 'agent', 'conf': '待核',
                     'dedupe_key': key, 'extraction_score': 0.7, 'durability_score': c.get('durability', 0.5),
                     'captured_at': __import__('time').strftime('%FT%T%z')})
    if not rows:
        return
    os.makedirs(os.path.join(SSOT, 'inbox', '.staging'), exist_ok=True)
    tmp = os.path.join(SSOT, 'inbox', '.staging', f"llm-{__import__('time').strftime('%F')}-{__import__('time').time_ns()%10000}.jsonl")
    with open(tmp, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    r = subprocess.run([sys.executable, os.path.join(SSOT, 'tools', 'sp_candidates.py'), '--ingest', tmp],
                       capture_output=True, text=True, cwd=SSOT)
    print('  账本:', (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else '?')
    print('  撞正本:留给批次末尾统一跑（避免每会话一次全量重扫）')


if __name__ == '__main__':
    sys.exit(main() or 0)

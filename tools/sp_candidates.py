#!/usr/bin/env python3
"""sp_candidates · 会话 → 候选命题库(缓冲层)v0.1(2026-10-25 立)

定位:抽取与登记**分离**。本器只产"候选",永不写 assertions/lines;
      人工/模型审后由 `--accept` 生成一条 inbox 行(仍走单向提纯)。

输入:evidence/<src>/S1-sessions/*/transcript.jsonl
输出:inbox/candidates/candidates.jsonl(按指纹去重、累计证据)
      inbox/candidates/review.md(待人审的候选清单)

判据(可复核):
  ① 同一命题在 N 个会话出现 → 只 1 条候选 + N 条 evidence
  ② 极性相反的同题候选 → 标 conflict,并并列证据
  ③ 跑完后 `git diff assertions.md` 为空(不越权)
用法:
  python3 sp_candidates.py --src all [--since 2026-10-20] [--min-score 3]
  python3 sp_candidates.py --src all --session <sid8> [--conflict-mode incremental]
  python3 sp_candidates.py --list
"""
import argparse, collections, datetime, glob, hashlib, json, math, os, re, sys, time, urllib.request

SSOT = os.path.expanduser('~/ssot')
OUTDIR = os.path.join(SSOT, 'inbox', 'candidates')
OUT = os.path.join(OUTDIR, 'candidates.jsonl')
REVIEW = os.path.join(OUTDIR, 'review.md')

# ---- 抽取规则:句子级,带权重 ----
PATTERNS = [
    (r'A\d{3,4}', 3),
    (r'(根因|判据|铁律|定案|拍板|结论|验证|实测|实证|实锤)', 2),
    (r'(决定|取舍|不采用|否决|改为|倾向)', 2),
    (r'\d+(\.\d+)?\s*(ms|s|min|h|GB|MB|KB|%|块|token|tokens|倍|x)', 2),
    (r'(必须|禁止|不许|永不|一律|只能)', 1),
    (r'(坑|踩坑|翻车|静默|不等价|失效)', 1),
]
TYPE_RULES = [
    ('decision', r'(决定|拍板|取舍|不采用|否决|改为|倾向)'),
    ('assertion', r'(铁律|判据|根因|必须|禁止|不许|永不|一律)'),
    ('fact', r'(实测|实证|实锤|验证)'),
]
POLARITY = [(r'(必须|应该|应当|需要|可以|能|允许|有收益|证明|确实)', +1),
            (r'(禁止|不许|不要|不能|别|否决|无收益|不该|不需要|不必|无需|不用|并非|不代表|不允许|不应该|没被证明)', -1)]


def norm(s):
    s = s.lower()
    s = re.sub(r'\d+(\.\d+)?', '<n>', s)
    s = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def fp(s):
    return hashlib.sha1(norm(s).encode('utf-8')).hexdigest()[:16]


def tokens(s):
    """中文按 2-gram,英文按词——中文没有空格,按词切会退化成整句一个 token"""
    n = norm(s)
    out = set()
    cjk = re.findall(r'[\u4e00-\u9fff]', n)
    out.update(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    out.update(w for w in re.findall(r'[a-z0-9_]{2,}', n))
    return out


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a, b):
    """重叠系数:适合"同一件事换个说法"(jaccard 会被新增修饰语压低)"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


NEG_RX = r'(禁止|不许|不要|不能|别|否决|无收益|不该|不需要|不必|无需|不用|并非|不代表|不允许|不应该|没被证明)'
POS_RX = r'(必须|应该|应当|需要|可以|能|允许|有收益|证明|确实|代表|足够|成功|就行|即可|等同于)'


def polarity(s):
    """先判否定:否定词常包含肯定词(如"不需要"含"需要"),同时计分会互相抵消 → 必须先否后肯。"""
    if re.search(NEG_RX, s):
        return -1
    if re.search(POS_RX, s):
        return +1
    return 0


def clean_claim(s):
    s = re.sub(r'^\s*(?:[-*+]|\d+[.)])\s*', '', s)
    s = re.sub(r'\*\*|__|`', '', s)
    return s.strip(' -—:：,，')


def rstrip_lines(s):
    return '\n'.join(line.rstrip() for line in str(s or '').splitlines())


def is_junk(s):
    if re.match(r'^\s*\|', s) or s.count('|') >= 3:
        return True
    if re.match(r'^\s*(道具|图示|表格|注[:：])', s):
        return True
    core = clean_claim(s)
    if len(core) < 12 or len(core) > 200:
        return True
    # 纯枚举/纯列表项(无谓语标记)不要
    if not re.search(r'[。；:：]|是|为|要|需|应|必须|禁|不|＝|=', core):
        return True
    return False


def sentences(text):
    for part in re.split(r'(?<=[。！？\n])', text or ''):
        p = part.strip()
        if 8 <= len(p) <= 220:
            yield p


def score_of(s):
    return sum(w for rx, w in PATTERNS if re.search(rx, s))


def guess_type(s):
    for t, rx in TYPE_RULES:
        if re.search(rx, s):
            return t
    return 'fact'


def load_index():
    out = {}
    if os.path.exists(OUT):
        for ln in open(OUT, encoding='utf-8'):
            ln = ln.strip()
            if not ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            out[o['fingerprint']] = o
    return out


def save_index(idx):
    os.makedirs(OUTDIR, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        for k in sorted(idx):
            f.write(json.dumps(idx[k], ensure_ascii=False) + '\n')


def sessions(src, since=None, needles=None):
    pats = [os.path.join(SSOT, 'evidence', src, 'S1-sessions', '*', 'transcript.jsonl')] if src != 'all' \
        else [os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*', 'transcript.jsonl')]
    out = []
    for p in pats:
        for f in glob.glob(p):
            name = os.path.basename(os.path.dirname(f))
            if needles and not any(n in name for n in needles):
                continue
            if since:
                d = name[:10]
                if d and d < since:
                    continue
            out.append(f)
    return sorted(out)


def mark_conflicts(idx, touched_ids, threshold=0.6):
    """Mark opposite-polarity near-neighbours without scanning every pair.

    Overlap-coefficient candidates are retrieved through an inverted token index.
    Only `touched_ids` initiate comparisons; existing candidates remain available
    as neighbours, so incremental extraction still sees the whole library.
    """
    candidates = {
        o['id']: o for o in idx.values()
        if o.get('state') == 'candidate' and o.get('polarity', 0) != 0
    }
    token_cache = {}
    by_polarity = {1: collections.defaultdict(list), -1: collections.defaultdict(list)}
    for cid, c in candidates.items():
        ts = tokens(c.get('claim', ''))
        token_cache[cid] = ts
        for token in ts:
            by_polarity[c['polarity']][token].append(cid)

    checked = 0
    touched = 0
    for cid in touched_ids:
        c = candidates.get(cid)
        if not c:
            continue
        touched += 1
        tc = token_cache[cid]
        if not tc:
            continue
        counts = collections.Counter()
        for token in tc:
            for other_id in by_polarity[-c['polarity']].get(token, ()):
                if other_id != cid:
                    counts[other_id] += 1
        for other_id, shared in counts.items():
            other = candidates.get(other_id)
            if not other:
                continue
            checked += 1
            denom = min(len(tc), len(token_cache[other_id]))
            if denom and shared / denom >= threshold:
                for x, y in ((c, other), (other, c)):
                    x['state'] = 'conflict'
                    links = x.setdefault('conflicts_with', [])
                    if y['id'] not in links:
                        links.append(y['id'])
    return checked, touched


def run(args):
    idx = load_index()
    added = merged = 0
    touched_ids = set()
    needles = []
    for raw in getattr(args, 'session', None) or []:
        needles.extend(x.strip() for x in raw.split(',') if x.strip())
    for tf in sessions(args.src, args.since, needles or None):
        sess = os.path.basename(os.path.dirname(tf))
        try:
            lines = open(tf, encoding='utf-8', errors='replace').read().splitlines()
        except Exception:
            continue
        for i, ln in enumerate(lines, 1):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            if o.get('kind') not in (None, 'text'):
                continue
            role = o.get('role') or ''
            if role not in ('user', 'assistant'):
                continue
            for s in sentences(o.get('content') or ''):
                if is_junk(s):
                    continue
                s = clean_claim(s)
                sc = score_of(s)
                if sc < args.min_score:
                    continue
                f = fp(s)
                ev = {'session': sess, 'line': i, 'role': role, 'quote': s[:140]}
                if f in idx:
                    c = idx[f]
                    if not any(e['session'] == sess and e['line'] == i for e in c['evidence']):
                        c['evidence'].append(ev)
                        merged += 1
                    c['score'] = max(c['score'], sc)
                else:
                    idx[f] = {'id': 'cand_' + f, 'claim': s, 'type': guess_type(s),
                              'fingerprint': f, 'score': sc, 'evidence': [ev],
                              'state': 'candidate', 'polarity': polarity(s),
                              'first_seen': sess,
                              'schema': 2,
                              'extracted_at': datetime.datetime.now().isoformat(timespec='seconds')}
                    added += 1
                    touched_ids.add('cand_' + f)
    # ---- 冲突检测:倒排近邻；默认只让本次新增项发起比较 ----
    items = sorted(idx.values(), key=lambda x: -x['score'])
    conflict_mode = getattr(args, 'conflict_mode', 'incremental')
    checked = scanned = 0
    if conflict_mode == 'full':
        touched_ids = {
            c['id'] for c in idx.values() if c.get('state') == 'candidate'
        }
    elif conflict_mode == 'none':
        touched_ids = set()
    if touched_ids:
        checked, scanned = mark_conflicts(idx, touched_ids, args.conflict_overlap)
        items = sorted(idx.values(), key=lambda x: -x['score'])
    save_index(idx)
    # ---- review.md ----
    os.makedirs(OUTDIR, exist_ok=True)
    with open(REVIEW, 'w', encoding='utf-8') as f:
        f.write(f"# 候选待审 · {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n")
        f.write(f"> 候选 {len(idx)} 条(candidate {sum(1 for x in idx.values() if x['state']=='candidate')} / "
                f"conflict {sum(1 for x in idx.values() if x['state']=='conflict')}) · 本次新增 {added} · 合并证据 {merged}\n")
        f.write("> 审校:`python3 tools/sp_candidates.py --accept <id>` 生成 inbox 行;`--reject <id> --reason …`\n\n")
        for c in items:
            if c['state'] not in ('candidate', 'conflict'):
                continue
            flag = ' ⚠️CONFLICT' if c['state'] == 'conflict' else ''
            f.write(f"## [{c['score']}] {c['type']}{flag} · {c['id']}\n\n{rstrip_lines(c['claim'])}\n\n")
            for e in c['evidence'][:3]:
                f.write(f"- `{e['session']}` L{e['line']} ({e['role']}) — {rstrip_lines(e['quote'][:100])}\n")
            f.write('\n')
    print(f'候选 {len(idx)} 条(candidate {sum(1 for x in idx.values() if x["state"]=="candidate")} / '
          f'conflict {sum(1 for x in idx.values() if x["state"]=="conflict")});新增 {added},合并证据 {merged}')
    print(f'冲突扫描:{conflict_mode} touched={scanned} neighbours_checked={checked}')
    print(f'→ {OUT}')
    print(f'→ {REVIEW}')


def accept(cid):
    idx = load_index()
    hit = [c for c in idx.values() if c['id'] == cid or c['fingerprint'] == cid]
    if not hit:
        sys.exit(f'未找到候选 {cid}')
    c = hit[0]
    c['state'] = 'accepted'
    save_index(idx)
    e = c['evidence'][0]
    line = (f"- {datetime.date.today()} [{c['type']}] {c['claim'][:400]} | "
            f"source: {e['session']}#L{e['line']} | line: 待定")
    print('已标记 accepted;把下面这行贴进 inbox(仍走单向提纯):\n')
    print(line)


def reject(cid, reason):
    idx = load_index()
    for c in idx.values():
        if c['id'] == cid or c['fingerprint'] == cid:
            c['state'] = 'rejected'
            c['reject_reason'] = reason
            c['rejected_at'] = datetime.datetime.now().isoformat(timespec='seconds')
            save_index(idx)
            print(f'已拒绝 {cid}:{reason}')
            return
    sys.exit(f'未找到候选 {cid}')


def review(state='candidate', offset=0, limit=10):
    """分页审阅:按分数降序,只列真候选(默认),带出处与证据数"""
    idx = load_index()
    items = [c for c in idx.values() if c['state'] == state]
    items.sort(key=lambda x: -x['score'])
    page = items[offset:offset + limit]
    print(f'# {state} · 共 {len(items)} 条 · 第 {offset+1}–{offset+len(page)} 条\n')
    for c in page:
        ev = c['evidence'][0] if c['evidence'] else {}
        print(f"[{c['score']}] {c['type']} · {c['id']}")
        print(f"   {c['claim'][:150]}")
        print(f"   出处 {ev.get('session','?')}#L{ev.get('line','?')} · 证据 {len(c['evidence'])} 条"
              + (f" · 已知 {c.get('assertion')}" if c.get('assertion') else ''))
        print()
    if offset + limit < len(items):
        print(f'… 下一页:--review {state} --offset {offset+limit} --limit {limit}')


def list_(limit=20):
    idx = load_index()
    items = sorted(idx.values(), key=lambda x: -x['score'])
    for c in items[:limit]:
        print(f"[{c['score']}][{c['type']}][{c['state']}] {c['claim'][:110]}")
    print(f'共 {len(idx)} 条')


EMB = 'http://127.0.0.1:8399/v1/embeddings'


def embed(texts, batch=16):
    out = []
    for i in range(0, len(texts), batch):
        body = json.dumps({'input': texts[i:i + batch]}).encode()
        req = urllib.request.Request(EMB, data=body, headers={'Content-Type': 'application/json'})
        d = json.load(urllib.request.urlopen(req, timeout=300))
        out.extend(x['embedding'] for x in d['data'])
    return out


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9) if na and nb else 0.0


def dedupe_l2(threshold_dup=0.92, threshold_rel=0.85, rel_max=3):
    """L2 向量近似:只在候选之间比(不碰正本),标 duplicate / related"""
    idx = load_index()
    items = [c for c in idx.values() if c['state'] in ('candidate', 'related')]
    if len(items) < 2:
        print('候选不足 2 条,跳过'); return
    try:
        vecs = embed([c['claim'] for c in items])
    except Exception as e:
        sys.exit(f'嵌入服务不可用({e});先起 llama-server :8399')
    dup = rel = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s = cos(vecs[i], vecs[j])
            if s >= threshold_dup:
                a, b = items[i], items[j]
                # 保留 score 高的,另一个折叠
                keep, drop = (a, b) if a['score'] >= b['score'] else (b, a)
                keep['evidence'] = keep['evidence'] + [e for e in drop['evidence']
                                                       if e not in keep['evidence']]
                drop['state'] = 'duplicate'
                drop['duplicate_of'] = keep['id']
                drop['l2_score'] = round(s, 3)
                dup += 1
            elif s >= threshold_rel:
                items[i].setdefault('_rel', []).append((s, items[j]['id']))
                items[j].setdefault('_rel', []).append((s, items[i]['id']))
                rel += 1
    for c in items:
        if '_rel' in c:
            c['related'] = [i for _, i in sorted(c.pop('_rel'), reverse=True)[:rel_max]]
    save_index(idx)
    print(f'L2:duplicate {dup} 对,related {rel} 对(仅存 top{rel_max}/条;阈值 {threshold_dup}/{threshold_rel})')


def _assertion_blocks():
    """解析 assertions.md → [(A编号, 标题+正文)]"""
    path = os.path.join(SSOT, 'knowledge', 'assertions.md')
    if not os.path.exists(path):
        return []
    txt = open(path, encoding='utf-8', errors='replace').read()
    out = []
    for m in re.finditer(r'^##\s*(A\d+)\s*[—\-·:：]?\s*([^\n]+)\n(.*?)(?=^##\s*A\d+|\Z)', txt, re.M | re.S):
        out.append((m.group(1), (m.group(2) + ' ' + m.group(3))[:400]))
    return out



def classify_vs_assertion(claim, block_text, score, threshold):
    """候选 vs 单条断言 → 'known' | 'conflict' | None

    2026-10-28 修:原实现只比相似度,撞上"反极性"的已知断言时会被误标 duplicate-known,
    把最有价值的冲突信号吞掉(见 drafts/opinion-on-auto-capture-review-2026-10-28 §2.5)。
    """
    if score < threshold:
        return None
    if polarity(claim) * polarity(block_text) < 0:
        return 'conflict'
    return 'known'

def against_assertions(threshold=0.88):
    """候选 vs 正本:防止同一结论被"重新发现"再入册一次(只读正本,不回写)"""
    idx = load_index()
    items = [c for c in idx.values() if c['state'] in ('candidate', 'related')]
    blocks = _assertion_blocks()
    if not items or not blocks:
        print('候选或断言为空,跳过'); return
    try:
        cv = embed([c['claim'] for c in items])
        av = embed([b[1] for b in blocks])
    except Exception as e:
        sys.exit(f'嵌入服务不可用({e})')
    known = 0
    ids = {b[0] for b in blocks}
    for c in items:
        refs = [x for x in re.findall(r'\bA\d{3}\b', c['claim']) if x in ids]
        if refs:
            c['state'] = 'duplicate-known'
            c['assertion'] = refs[0]
            c['assertion_score'] = 1.0
            c['match_rule'] = 'explicit'
            known += 1
    for i, c in enumerate(items):
        if c['state'] == 'duplicate-known':
            continue
        best, bi = 0.0, -1
        for j, v in enumerate(av):
            s = cos(cv[i], v)
            if s > best:
                best, bi = s, j
        verdict = classify_vs_assertion(c['claim'], blocks[bi][1], best, threshold)
        if verdict:
            c['state'] = 'duplicate-known' if verdict == 'known' else 'conflict'
            c['assertion'] = blocks[bi][0]
            c['assertion_score'] = round(best, 3)
            c['match_rule'] = 'vector' if verdict == 'known' else 'vector-polarity'
            known += (verdict == 'known')
    save_index(idx)
    conf = sum(1 for c in items if c['state'] == 'conflict')
    print(f'vs 正本:{known}/{len(items)} 条候选已是已知断言(阈值 {threshold}),标 duplicate-known 并附 A 编号')
    if conf:
        print(f'⚠ 反极性命中 {conf} 条 → 标 conflict(不是 duplicate-known),进 review 优先裁决')



def selftest_aa():
    """合成对:同一命题的正/反表述,要求分类正确的是 conflict,不是 known"""
    pairs = [
        ('必须上向量数据库,否则检索太慢', '不需要上向量数据库,暴力检索在本量级足够'),
        ('批量接口返回 2xx 就代表执行成功', '批量接口返回 2xx 不代表执行成功,必须逐条核对'),
        ('阈值用直觉定就行', '阈值必须按真实分布校准,不能用直觉'),
    ]
    ok = 0
    for a_, b_ in pairs:
        v = classify_vs_assertion(a_, b_, 1.0, 0.88)
        good = (v == 'conflict')
        print(f'  polarity=({polarity(a_)},{polarity(b_)}) → {v} {"✅" if good else "❌"}')
        ok += good
    same = classify_vs_assertion('必须上向量数据库否则太慢', '必须上向量数据库,否则检索太慢', 1.0, 0.88)
    print(f'  同向 → {same} {"✅" if same == "known" else "❌"}')
    ok += (same == 'known')
    print(f'冲突检测单测:{ok}/{len(pairs)+1}')
    return 0 if ok == len(pairs) + 1 else 2


def ingest(path, dry=False):
    """消费 sp_capture 产出的 cand.v1 staging → 现有 candidates.jsonl(单向映射)"""
    import glob
    files = [path] if path and os.path.isfile(path) else sorted(glob.glob(os.path.join(os.path.dirname(path or 'inbox/.staging/x'), '*.jsonl')))
    idx = load_index()
    have = {c.get('fingerprint') for c in idx.values()} | {c['id'] for c in idx.values()}
    add, dup, bad = 0, 0, 0
    for f in files:
        for ln in open(f, encoding='utf-8'):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                bad += 1
                continue
            if d.get('schema') != 'cand.v1' or not d.get('claim') or not d.get('source'):
                bad += 1
                continue
            fp = d.get('dedupe_key') or ''
            if fp in have or d['id'] in have:
                dup += 1
                continue
            sid, rest = d['source'].split('#', 1)
            msgid, line = rest.rsplit('@L', 1) if '@L' in rest else (rest, '0')
            cid = d['id']
            idx[cid] = {
                'id': cid,
                'type': d['type'],
                'claim': d['claim'],
                'score': int(round(float(d.get('extraction_score', 0.6)) * 10)),
                'state': 'candidate',
                'polarity': polarity(d['claim']),
                'fingerprint': fp,
                'first_seen': d.get('captured_at', ''),
                'extracted_at': time.strftime('%F %T'),
                'evidence': [{'session': sid.replace('session:', ''), 'line': int(line),
                              'role': d.get('owner', 'agent') == 'user' and 'user' or 'assistant',
                              'quote': d.get('quote', '')[:200],
                              'message_id': msgid, 'quote_sha1': d.get('quote_sha1', '')}],
                'origin': d.get('origin', 'batch-s1'),
                'capture_reason': d.get('capture_reason', ''),
                'related': [],
                'schema': 2,
            }
            have.add(fp); have.add(cid)
            add += 1
    if not dry:
        save_index(idx)
    print(f'ingest:{add} 新增 / {dup} 重复丢弃 / {bad} 不合规' + ('(dry-run)' if dry else ''))
    return 0 if bad == 0 else 2

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_contract import guard as _contract_guard
    if not _contract_guard('sp_candidates', write=True):
        return 2
    ap = argparse.ArgumentParser(
    epilog='【契约】意图：把候选从账本里筛选/去重/撞正本；只读正本，永不写断言\n退出码：0=正常；2=实例契约不符（先跑 sp_migrate）\n失败后：契约不符→sp_migrate --to current；冲突→看 --review\n\n示例:\n  sp_candidates.py --src dsh --min-score 5      # 从 DSH 会话抽候选\n  sp_candidates.py --against-assertions         # 撞正本(先做!已知断言占比通常很高)\n  sp_candidates.py --dedupe-l2                  # 候选间 L2 去重(0.92/0.85,related top3)\n  sp_candidates.py --review candidate --limit 10\n  sp_candidates.py --accept cand_xxx            # 只打印 inbox 行,不写正本\n  sp_candidates.py --selftest                   # 冲突检测自检\n\n纪律:抽取器永不写 assertions/lines。\n顺序:撞正本 → 候选间去重 → 冲突 → 人工审(见 A421)。',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', default='all', help='qoder|cc|pi|dsh|all')
    ap.add_argument('--since', help='YYYY-MM-DD,会话目录日期前缀过滤')
    ap.add_argument('--session', action='append', help='只扫描目录名含该前缀/片段的会话；可重复或逗号分隔')
    ap.add_argument('--min-score', type=int, default=3)
    ap.add_argument('--conflict-overlap', type=float, default=0.6)
    ap.add_argument('--conflict-mode', choices=['incremental', 'full', 'none'], default='incremental',
                    help='incremental=只比较本次新增(默认); full=倒排重建全部 candidate; none=跳过冲突扫描')
    ap.add_argument('--list', nargs='?', const=20, type=int)
    ap.add_argument('--review', nargs='?', const='candidate')
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--accept')
    ap.add_argument('--reject')
    ap.add_argument('--reason', default='')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--selftest-aa', action='store_true', help='冲突检测单测:撞已知断言但反极性 → conflict')
    ap.add_argument('--ingest', metavar='PATH', help='消费 cand.v1 staging 文件(或同目录)')
    ap.add_argument('--dedupe-l2', action='store_true')
    ap.add_argument('--against-assertions', action='store_true')
    ap.add_argument('--aa-threshold', type=float, default=0.88)
    ap.add_argument('--l2-dup', type=float, default=0.92)
    ap.add_argument('--l2-rel', type=float, default=0.85)
    a = ap.parse_args()
    if a.selftest:
        a1 = '索引重建必须搬到 GPU 节点跑,收益 9 倍'
        b1 = '索引重建不该搬到 GPU 节点跑,收益被带宽吃掉'
        ta, tb = tokens(a1), tokens(b1)
        ok = (overlap(ta, tb) >= a.conflict_overlap) and (polarity(a1) * polarity(b1) < 0)
        print(f'overlap={overlap(ta,tb):.3f} polarity=({polarity(a1)},{polarity(b1)}) → 冲突可检出:{"✅" if ok else "❌"}')
        sys.exit(0 if ok else 1)
    if a.ingest:
        return ingest(a.ingest)
    if a.selftest_aa:
        return selftest_aa()
    if a.against_assertions:
        return against_assertions(a.aa_threshold)
    if a.dedupe_l2:
        return dedupe_l2(a.l2_dup, a.l2_rel)
    if a.review:
        return review(a.review, a.offset, a.limit)
    if a.list is not None:
        return list_(a.list)
    if a.accept:
        return accept(a.accept)
    if a.reject:
        return reject(a.reject, a.reason)
    run(a)


if __name__ == '__main__':
    sys.exit(main())

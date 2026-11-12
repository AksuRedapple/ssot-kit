#!/usr/bin/env python3
"""sp_presets · 转生 preset 的加载与校验(供 sp_handoff / sp_dispatch 共用)

preset = 命名组合:主工作线 + 断言 tag 子集 + open-loop 档位 + 预算。
核心判据:**被引用的东西必须真实存在**,失效就报错,不静默省略。
"""
import json, os, re

SSOT = os.path.expanduser('~/ssot')
FILE = os.path.join(SSOT, 'profile', 'presets.json')


def load(path=FILE):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def line_exists(slug):
    return bool(slug) and os.path.isfile(os.path.join(SSOT, 'lines', slug + '.md'))


def assertions_by_tags(tags):
    """→ [(A 号, 标题, 正文)]；tag 命中即选（逗号/顿号分隔的都算）"""
    p = os.path.join(SSOT, 'knowledge', 'assertions.md')
    if not tags or not os.path.exists(p):
        return []
    blocks, cur, buf = [], None, []
    for ln in open(p, encoding='utf-8', errors='replace'):
        if ln.startswith('## A'):
            if cur:
                blocks.append((cur, '\n'.join(buf)))
            m = re.match(r'## (A\d{3})\s*[·—\-]?\s*(.*)', ln.strip())
            cur = (m.group(1), m.group(2)) if m else (ln.strip()[3:6], ln.strip())
            buf = []
        elif cur:
            buf.append(ln.rstrip())
    if cur:
        blocks.append((cur, '\n'.join(buf)))
    out = []
    want = [t.strip() for t in tags if t.strip()]
    for (num, _title), body in blocks:
        tags_line = re.search(r'标签\*{0,2}\s*[:：]\s*(.+)', body)
        tagtext = tags_line.group(1) if tags_line else ''
        if any(w and w in tagtext for w in want):
            out.append((num, body.splitlines()[0][:60] if body else '', body))
    return out


def assertion_by_id(num):
    p = os.path.join(SSOT, 'knowledge', 'assertions.md')
    if not os.path.exists(p):
        return None
    body, cur = [], None
    for ln in open(p, encoding='utf-8', errors='replace'):
        if ln.startswith('## A'):
            if cur == num:
                return '\n'.join(body)
            mm = re.match(r'## (A\d{3})', ln)
            cur = mm.group(1) if mm else cur
            body = [ln.rstrip()]
        elif cur:
            body.append(ln.rstrip())
    return '\n'.join(body) if cur == num else None


def openloop_items(tier='A'):
    p = os.path.join(SSOT, 'knowledge', 'open-loops.md')
    if not os.path.exists(p):
        return []
    items, inA = [], False
    for ln in open(p, encoding='utf-8', errors='replace'):
        if ln.startswith('## A'):
            inA = True; continue
        if ln.startswith('## '):
            inA = False; continue
        if tier == 'A' and inA and ln.startswith('- '):
            items.append(ln.rstrip()[2:])
    return items


def validate(name, presets=None):
    """→ 错误列表(空=通过)"""
    presets = presets or load()
    if name not in presets:
        return [f'preset 不存在:{name}']
    p = presets[name]
    errs = []
    if p.get('line') and not line_exists(p['line']):
        errs.append(f'线页不存在:lines/{p["line"]}.md')
    tags = p.get('assert_tags') or []
    if tags and not assertions_by_tags(tags):
        errs.append(f'断言 tag 无命中:{tags}')
    for aid in p.get('asserts') or []:
        if not assertion_by_id(aid):
            errs.append(f'断言号不存在:{aid}')
    for ref in re.findall(r'\bA\d{3}\b', json.dumps(p, ensure_ascii=False)):
        known = set(re.findall(r'^## (A\d{3})', open(os.path.join(SSOT, 'knowledge', 'assertions.md'), encoding='utf-8').read(), re.M))
        if ref not in known:
            errs.append(f'断言号不存在:{ref}')
    if p.get('openloop') == 'A' and not openloop_items('A'):
        errs.append('open-loops A 档为空')
    return errs


def brief(name, presets=None):
    """给 dispatch/handoff 用的一段摘要文本"""
    presets = presets or load()
    p = presets[name]
    out = [f'preset:{name} — {p.get("desc","")}']
    if p.get('line'):
        f = os.path.join(SSOT, 'lines', p['line'] + '.md')
        out.append(f'主线页:{p["line"]}（{os.path.getsize(f)} B）')
    ids = p.get('asserts') or []
    asrt = [(aid, '') for aid in ids if assertion_by_id(aid)]
    tags = p.get('assert_tags') or []
    if tags:
        asrt += assertions_by_tags(tags)
    if asrt:
        out.append(f'相关断言:{len(asrt)} 条（{", ".join(a for a, _ in asrt[:8])}{"…" if len(asrt) > 8 else ""}）')
    ol = openloop_items(p.get('openloop', 'A'))
    out.append(f'未尽事项:{len(ol)} 条（A 档）')
    return '\n'.join(out), len(asrt) if tags else 0, len(ol)

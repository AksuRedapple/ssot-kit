"""断言正本解析：A 编号、状态、标签、取代关系、体检统计（唯一实现）。

此前 `^## A\\d+` 在 ssot_check / sp_assert_alloc / sp_compile / sp_assert_lib
各有一份，改一处漏一处。此后断言解析只允许从这里引用。
"""
import json
import os
import re

HEAD_RX = re.compile(r'^##\s*(A\d+[a-z]?)\s*(?:[·:：—\-]\s*)?(.*)$')
NUM_RX = re.compile(r'^## A(\d+)', re.M)
ID_RX = re.compile(r'^## A(\d+)([a-z]?)', re.M)
STATUS_RX = re.compile(r'状态[：:]\s*([^｜|\n]+)')
SUP_RX = re.compile(r'(?:superseded_by|取代[：:])\s*[：:]?\s*(A\d+[a-z]?)', re.I)
TAG_RX = re.compile(r'标签[：:]\s*([^｜|\n]+)')
CITE_RX = re.compile(r'\bA\d{3}[a-z]?\b')
TAG_COUNT_RX = re.compile(r'标签[:：]')

STATUS_MAP = {
    '现役': 'active',
    '已内化': 'active',
    '已过时': 'superseded',
    '已废弃': 'superseded',
    '已失效': 'superseded',
    '失效': 'superseded',
    '空号': 'vacant',
    '已修': 'active',
    '修复在': 'active',
    '部分失效': 'active',
}


def base_status(raw):
    raw = (raw or '').strip()
    m = re.match(r'([^（(｜|\s]+)', raw)
    return m.group(1) if m else raw


def parse_text(text):
    """→ [{id,title,line,end,lines,text,chars,status_raw,status_base,status,tags,superseded_by}]"""
    blocks, cur = [], None
    for i, line in enumerate((text or '').splitlines(), 1):
        m = HEAD_RX.match(line)
        if m:
            if cur:
                blocks.append(cur)
            cur = {'id': m.group(1), 'title': m.group(2).strip(),
                   'line': i, 'lines': [line]}
        elif cur is not None:
            cur['lines'].append(line)
    if cur:
        blocks.append(cur)
    for b in blocks:
        text = '\n'.join(b['lines'])
        b['text'] = text
        b['chars'] = len(text)
        b['end'] = b['line'] + len(b['lines']) - 1
        sm = STATUS_RX.search(text)
        raw = sm.group(1).strip() if sm else ''
        b['status_raw'] = raw
        b['status_base'] = base_status(raw)
        b['status'] = STATUS_MAP.get(b['status_base'], 'unknown')
        tm = TAG_RX.search(text)
        b['tags'] = [x.strip() for x in tm.group(1).split(',') if x.strip()] if tm else []
        supm = SUP_RX.search(text)
        b['superseded_by'] = supm.group(1) if supm else ''
    return blocks


def parse(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return []
    return parse_text(text)


def ids(text):
    """→ [(数字, 后缀)]，按出现顺序；后缀为空串（A515b 的 b）。"""
    return [(int(n), s) for n, s in ID_RX.findall(text or '')]


def numbers(text):
    """→ [数字]（忽略后缀）；给「最大号」类逻辑用。"""
    return [int(n) for n in NUM_RX.findall(text or '')]


def reserved_ids(root):
    """分配器预留但尚未 commit 的编号（不参与缺号统计）。"""
    try:
        d = json.load(open(os.path.join(root, 'profile', '.assert-alloc.json'), encoding='utf-8'))
        return set(int(x) for x in d.get('reserved', []))
    except Exception:
        return set()


def lint(root):
    """断言体检计数：总数/最新/重号/缺号/标签数（只报不改号）。"""
    p = os.path.join(root, 'knowledge', 'assertions.md')
    if not os.path.exists(p):
        return {'total': 0}
    with open(p, encoding='utf-8', errors='replace') as f:
        txt = f.read()
    pairs = ids(txt)
    if not pairs:
        return {'total': 0}
    nums = [n for n, _s in pairs]
    full = [f'A{n}{s}' for n, s in pairs]
    seen = set(nums)
    dup_counts = {}
    for x in full:
        dup_counts[x] = dup_counts.get(x, 0) + 1
    reserved = reserved_ids(root)
    return {
        'total': len(nums),
        'latest': max(nums),
        'dups': len(full) - len(set(full)),
        'dup_ids': sorted(k for k, v in dup_counts.items() if v > 1),
        'missing': len([i for i in range(1, max(nums) + 1)
                        if i not in seen and i not in reserved]),
        'missing_ids': [i for i in range(1, max(nums) + 1) if i not in seen],
        'tags': len(TAG_COUNT_RX.findall(txt)),
    }

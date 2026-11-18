#!/usr/bin/env python3
"""sp_assert_lib · assertions.md 解析（audit / meta / index 共用）"""
import re

HEAD_RX = re.compile(r'^##\s*(A\d+[a-z]?)\s*(?:[·:：—\-]\s*)?(.*)$')
STATUS_RX = re.compile(r'状态[：:]\s*([^｜|\n]+)')
SUP_RX = re.compile(r'(?:superseded_by|取代[：:])\s*[：:]?\s*(A\d+[a-z]?)', re.I)
TAG_RX = re.compile(r'标签[：:]\s*([^｜|\n]+)')
CITE_RX = re.compile(r'\bA\d{3}[a-z]?\b')

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


def parse(path):
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return []
    blocks, cur = [], None
    for i, line in enumerate(lines, 1):
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

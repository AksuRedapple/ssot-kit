#!/usr/bin/env python3
"""sp_drafts · 收尾草稿 → registry 候选行（只读，不自动转正）

判据（2026-11-18）：草稿只有 sid/cwd/时间，没有标题与需求线；
因此这里只做两件事：列清单、打印候选行。绝不 append、绝不改 registry。

用法:
  python3 tools/sp_drafts.py --list [--json]
  python3 tools/sp_drafts.py --candidate <sid8>

转正仍由人确认：复制候选行 → 补 line/tags → 手工 append 到 sessions/registry.md。
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
PENDING = os.path.join(SSOT, 'sessions', '_pending')
REGISTRY = os.path.join(SSOT, 'sessions', 'registry.md')


def parse_draft(path):
    """草稿每行: - YYYY-MM-DD HH:MM:SS | sid: <uuid> | cwd: <path>"""
    sid, cwd, ts = None, '-', '-'
    try:
        for line in open(path, encoding='utf-8', errors='replace'):
            m = re.match(r'^-\s+(\S+ \S+)\s+\|\s+sid:\s*(\S+)\s+\|\s+cwd:\s*(.*)$', line.rstrip('\n'))
            if not m:
                continue
            ts, sid, cwd = m.group(1), m.group(2), (m.group(3) or '-').strip()
    except OSError:
        pass
    return {'sid': sid, 'sid8': os.path.basename(path)[:8], 'cwd': cwd, 'ts': ts}


def find_s1(sid8):
    """只有带 meta.json 的目录才算完成 S1；空目录/半成品不算。"""
    hits = sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', f'*{sid8}*')))
    for d in hits:
        if os.path.isdir(d) and os.path.exists(os.path.join(d, 'meta.json')):
            return d
    return None


def read_meta(s1dir):
    try:
        return json.load(open(os.path.join(s1dir, 'meta.json'), encoding='utf-8'))
    except Exception:
        return {}


def first_user_text(s1dir, limit=80):
    p = os.path.join(s1dir, 'transcript.jsonl')
    try:
        for line in open(p, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('role') != 'user' or d.get('kind') not in (None, 'text'):
                continue
            txt = ' '.join(str(d.get('content') or '').split())
            if not txt or txt.startswith(('<system-reminder>', '[Request interrupted', 'Caveat:')):
                continue
            return txt[:limit]
    except OSError:
        pass
    return ''


def one_line(s):
    return ' '.join((s or '-').replace('|', '/').split())


def registry_row(draft, meta, summary):
    sid = meta.get('sid') or draft.get('sid') or '-'
    start = meta.get('start') or ''
    try:
        date = datetime.datetime.fromisoformat(start.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except Exception:
        date = (draft.get('ts') or '-')[:16]
    title = one_line(meta.get('title') or '-')
    cwd = one_line(meta.get('cwd') or draft.get('cwd') or '-')
    return f"- {date} | {title} | {sid} | {cwd} | {one_line(summary) or '-'} | active | - | tags:- | line:待归类 | memo:-"


def cmd_list(as_json=False):
    files = sorted(glob.glob(os.path.join(PENDING, '*.md')))
    rows = []
    for p in files:
        d = parse_draft(p)
        s1 = find_s1(d['sid8'])
        meta = read_meta(s1) if s1 else {}
        d.update({'has_s1': bool(s1), 'title': one_line(meta.get('title') or '-')[:40]})
        rows.append(d)
    if as_json:
        print(json.dumps({'pending': len(files), 'rows': rows}, ensure_ascii=False, indent=1))
        return 0
    print(f"待转正草稿 {len(files)} 份（只读；转正仍走人工确认）")
    for r in rows:
        print(f"{r['sid8']}  {r['ts']:<19}  S1={'Y' if r['has_s1'] else 'N'}  {r['cwd']}  {r['title']}")
    return 0


def cmd_candidate(sid8):
    p = os.path.join(PENDING, sid8 + '.md')
    if not os.path.exists(p):
        hits = sorted(glob.glob(os.path.join(PENDING, sid8 + '*.md')))
        if len(hits) != 1:
            print(f"未找到唯一草稿：{sid8}", file=sys.stderr)
            return 2
        p = hits[0]
    d = parse_draft(p)
    s1 = find_s1(d['sid8'])
    if not s1:
        print(f"该会话还没有 S1（{d['sid8']}）；先跑 sp_convert，再生成候选行。", file=sys.stderr)
        return 2
    meta = read_meta(s1)
    print(registry_row(d, meta, first_user_text(s1)))
    return 0


def main():
    ap = argparse.ArgumentParser(
        epilog='示例:\n  sp_drafts.py --list\n  sp_drafts.py --candidate 1a2b3c4d',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--candidate', metavar='SID8')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.candidate:
        return cmd_candidate(a.candidate)
    if a.list:
        return cmd_list(a.json)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())

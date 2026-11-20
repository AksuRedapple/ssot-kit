#!/usr/bin/env python3
"""sp_recall · 关键词兜底检索（不依赖索引）

分工：
  sp_semantic —— 记得大意、不记得词；
  sp_recall   —— 记得词，或索引未建/落后/损坏。

数据源（优先级）：
  1) evidence/<h>/S1-sessions/*/transcript.jsonl（已抽取、已脱敏）
  2) --raw：evidence/<h>/S0-archive/**/*.jsonl（未抽取原文，输出前脱敏）
  3) --live：harness 真源（sp_sources 发现；jsonl 直接读，sqlite 不读）

用法:
  python3 tools/sp_recall.py "关键词" [--harness all|qoder|cc|dsh|pi|codex]
                              [--ctx 300] [--limit 20] [--since 30d]
                              [--raw] [--live] [--json] [--ignore-case]

退出码：0=有命中；1=无命中；2=参数/正则错误。
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import sources as sp_sources  # noqa: E402
from ssotlib import cli  # noqa: E402

SSOT = sp_sources.SSOT
ROLES = ('qoder', 'cc', 'dsh', 'pi', 'codex')

try:
    from ssotlib.ingest import scrub as _scrub
except Exception:  # pragma: no cover
    def _scrub(s):
        return s


def one_line(s, limit=None):
    s = ' '.join(str(s).replace('\x00', ' ').split())
    return s[:limit] if limit and len(s) > limit else s


def snippet(text, m, ctx):
    a = max(0, m.start() - ctx)
    b = min(len(text), m.end() + ctx)
    return ('…' if a else '') + one_line(text[a:b]) + ('…' if b < len(text) else '')


SID_DIR = re.compile(r'^\d{4}-\d{2}-\d{2}-([0-9a-f]{8})')


def sid_of(path):
    base = os.path.basename(path)
    if base == 'transcript.jsonl':
        m = SID_DIR.match(os.path.basename(os.path.dirname(path)))
        return m.group(1) if m else os.path.basename(os.path.dirname(path))[:8]
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', base)
    if m:
        return m.group(1)[:8]
    return base.split('.')[0][:8]


def texts(d):
    """从各 harness 的 JSONL 行里取可读文本（尽力而为，不追求全格式）。"""
    if not isinstance(d, dict):
        return []
    out = []
    msg = d.get('message') if isinstance(d.get('message'), dict) else d
    c = msg.get('content') if isinstance(msg, dict) else None
    if isinstance(c, str):
        out.append(c)
    elif isinstance(c, list):
        for x in c:
            if isinstance(x, dict) and isinstance(x.get('text'), str):
                out.append(x['text'])
    for k in ('text', 'content'):
        v = d.get(k)
        if isinstance(v, str) and v not in out:
            out.append(v)
    return out


def meta_of(d):
    if not isinstance(d, dict):
        return '-', '-'
    msg = d.get('message') if isinstance(d.get('message'), dict) else {}
    role = d.get('role') or msg.get('role') or d.get('type') or '-'
    ts = (d.get('t') or d.get('ts') or d.get('timestamp')
          or msg.get('timestamp') or '-')
    return str(role), str(ts)


def scan_s1(only, rx, ctx, since, hits, seen):
    for h in only:
        base = os.path.join(SSOT, 'evidence', h, 'S1-sessions')
        if not os.path.isdir(base):
            continue
        for d in sorted(os.listdir(base)):
            p = os.path.join(base, d, 'transcript.jsonl')
            if not os.path.isfile(p):
                continue
            if since and os.path.getmtime(p) < since:
                continue
            sid = sid_of(p)
            try:
                for ln, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
                    if not rx.search(line):
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    content = '\n'.join(texts(o))
                    m = rx.search(content)
                    if not m:
                        continue
                    role, ts = meta_of(o)
                    snip = snippet(content, m, ctx)
                    key = (sid, one_line(snip, 120))
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append({'harness': h, 'sid': sid, 'file': p, 'line': ln,
                                 'ts': ts, 'role': role, 'snippet': snip, 'layer': 'S1'})
            except OSError:
                continue


def scan_s0(only, rx, ctx, since, hits, seen):
    for h in only:
        base = os.path.join(SSOT, 'evidence', h, 'S0-archive')
        if not os.path.isdir(base):
            continue
        for dirpath, _dn, filenames in os.walk(base):
            for fn in filenames:
                if not fn.endswith('.jsonl'):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if since and os.path.getmtime(p) < since:
                        continue
                except OSError:
                    continue
                sid = sid_of(p)
                try:
                    for ln, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
                        if not rx.search(line):
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            o = None
                        content = '\n'.join(texts(o)) if o else line
                        m = rx.search(content)
                        if not m:
                            continue
                        role, ts = meta_of(o) if o else ('-', '-')
                        snip = snippet(content, m, ctx)
                        key = (sid, one_line(snip, 120))
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append({'harness': h, 'sid': sid, 'file': p, 'line': ln,
                                     'ts': ts, 'role': role, 'snippet': snip, 'layer': 'S0'})
                except OSError:
                    continue


def scan_live(only, rx, ctx, since, hits, seen):
    for h, p, _size, _mt in sp_sources.iter_files(only, since):
        if h not in only or not p.endswith('.jsonl'):
            continue
        sid = sid_of(p)
        try:
            for ln, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
                if not rx.search(line):
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                content = '\n'.join(texts(o))
                m = rx.search(content)
                if not m:
                    continue
                role, ts = meta_of(o)
                snip = snippet(content, m, ctx)
                key = (sid, one_line(snip, 120))
                if key in seen:
                    continue
                seen.add(key)
                hits.append({'harness': h, 'sid': sid, 'file': p, 'line': ln,
                             'ts': ts, 'role': role, 'snippet': snip, 'layer': 'live'})
        except OSError:
            continue


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_recall.py "dsh-fastlane"\n  sp_recall.py "密钥" --raw --json', root=False)
    ap.add_argument('pattern')
    ap.add_argument('--harness', default='all', help='all 或逗号分隔（qoder,cc,dsh,pi,codex）')
    ap.add_argument('--ctx', type=int, default=300, help='命中前后各保留字符数（默认 300）')
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--since', help='只查最近变更，如 30d / 12h')
    ap.add_argument('--raw', action='store_true', help='追加 S0 原始归档（未抽取，输出前脱敏）')
    ap.add_argument('--live', action='store_true', help='追加 harness 真源（jsonl）')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--ignore-case', action='store_true')
    a = ap.parse_args()

    only = set(ROLES) if a.harness == 'all' else set(x.strip() for x in a.harness.split(',') if x.strip())
    bad = only - set(ROLES)
    if bad:
        print(f"未知 harness: {','.join(sorted(bad))}", file=sys.stderr)
        return 2
    try:
        rx = re.compile(a.pattern, re.I if a.ignore_case else 0)
    except re.error as e:
        print(f"正则错误: {e}", file=sys.stderr)
        return 2
    since = sp_sources.parse_since(a.since)
    hits, seen = [], set()
    t0 = time.time()
    scan_s1(only, rx, a.ctx, since, hits, seen)
    if a.raw:
        scan_s0(only, rx, a.ctx, since, hits, seen)
    if a.live:
        scan_live(only, rx, a.ctx, since, hits, seen)
    hits.sort(key=lambda r: os.path.getmtime(r['file']) if os.path.exists(r['file']) else 0, reverse=True)
    hits = hits[:a.limit]
    for r in hits:
        r['snippet'] = _scrub(r['snippet'])
    out = {'query': a.pattern, 'count': len(hits), 'ms': int((time.time() - t0) * 1000),
           'layers': ['S1'] + (['S0'] if a.raw else []) + (['live'] if a.live else []),
           'hits': hits}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"query: {a.pattern} · 命中 {len(hits)} · {out['ms']}ms · 层 {','.join(out['layers'])}")
        for r in hits:
            print(f"\n[{r['layer']}] {r['harness']}/{r['sid']} · {r['role']} · {r['ts']}")
            print(f"  {os.path.relpath(r['file'], SSOT)}:{r['line']}")
            print(f"  {r['snippet']}")
        if not hits:
            print('  （S1 无命中；可加 --raw 查未抽取原文，或 --live 查 harness 真源）')
    return 0 if hits else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""sp_retire_candidates · 零命中退休候选（只读，不自动删）

数据来源：S2-index/search-log.jsonl（sp_semantic 的 topk_paths/topk_sids）。
判据：窗口内从未出现在 top-k 的已索引会话 → 候选；人工确认后走 sp_exit。

用法:
  python3 tools/sp_retire_candidates.py
  python3 tools/sp_retire_candidates.py --days 180 --json
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import policy as sp_policy  # noqa: E402
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
LOG = os.path.join(SSOT, 'S2-index', 'search-log.jsonl')
SID_RX = re.compile(r'/(?:S1-sessions|S1-subagents)/(?:\d{4}-\d{2}-\d{2}-)?([0-9a-f]{8})')


def _ts(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0


def load_hits(days):
    cutoff = datetime.datetime.now().timestamp() - days * 86400
    hits, logs = set(), 0
    try:
        for line in open(LOG, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            tool = str(d.get('tool', ''))
            if not (tool.startswith('sp_semantic') or tool == 'sp_search'):
                continue
            if _ts(d.get('ts')) < cutoff:
                continue
            logs += 1
            for sid in d.get('topk_sids') or []:
                hits.add(str(sid)[:8])
            for p in d.get('topk_paths') or []:
                m = SID_RX.search(str(p))
                if m:
                    hits.add(m.group(1))
            p = d.get('top1_path')
            if p:
                m = SID_RX.search(str(p))
                if m:
                    hits.add(m.group(1))
    except OSError:
        pass
    return hits, logs


def sessions():
    policy = sp_policy.load_policy(SSOT)
    retired, _ = sp_policy.load_retired(SSOT)
    out = []
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions'))):
        harness = os.path.basename(os.path.dirname(top))
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            mp = os.path.join(d, 'meta.json')
            if not os.path.isfile(mp):
                continue
            try:
                m = json.load(open(mp, encoding='utf-8'))
            except Exception:
                continue
            rel = os.path.relpath(d, SSOT)
            sid = sp_policy.sid_of(m, rel)
            cls = sp_policy.class_of(m)
            if sid in retired or not sp_policy.included(cls, policy):
                continue
            out.append({'sid': sid, 'sid8': sid[:8], 'harness': harness,
                        'date': str(m.get('start') or '')[:10], 'class': cls,
                        'title': (m.get('title') or '')[:60]})
    return out


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_retire_candidates.py --days 180', root=False)
    ap.add_argument('--days', type=int, default=180)
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--min-logs', type=int, default=20, help='少于该日志数时标记低置信')
    ap.add_argument('--min-coverage', type=float, default=0.2, help='命中会话占比低于该值时标记低置信')
    ap.add_argument('--exclude-title', help='排除标题命中的正则（只影响报告）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    hits, logs = load_hits(a.days)
    all_s = sessions()
    ex = re.compile(a.exclude_title, re.I) if a.exclude_title else None
    excluded = 0
    if ex:
        kept = []
        for s in all_s:
            if ex.search(s['title']):
                excluded += 1
            else:
                kept.append(s)
        all_s = kept
    zero = [s for s in all_s if s['sid8'] not in hits]
    now = datetime.datetime.now().astimezone()
    out = {'window_days': a.days,
           'window_end': now.isoformat(timespec='seconds'),
           'window_start': (now - datetime.timedelta(days=a.days)).isoformat(timespec='seconds'),
           'logs': logs, 'min_logs': a.min_logs, 'min_coverage': a.min_coverage,
           'sessions': len(all_s), 'excluded_titles': excluded,
           'hit_sids': len(hits), 'zero_hit': len(zero),
           'coverage': round(len(hits) / max(1, len(all_s)), 3),
           'candidates': zero[:a.limit]}
    out['low_confidence'] = (logs < a.min_logs or out['coverage'] < a.min_coverage)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"window {a.days}d · logs {logs} · sessions {len(all_s)} · "
              f"hit {len(hits)} · zero-hit {len(zero)} · coverage {out['coverage']:.1%}")
        if out['low_confidence']:
            print(f"  ⚠ 数据不足（logs {logs}/{a.min_logs}，coverage {out['coverage']:.1%}/{a.min_coverage:.0%}），候选仅供参考")
        if a.exclude_title:
            print(f"  排除标题 {excluded} 条")
        if not logs:
            print("  （还没有 top-k 日志；先让 sp_semantic 正常记录）")
        for s in zero[:a.limit]:
            print(f"  {s['sid8']}  {s['date']}  {s['class']:10s}  {s['title']}")
        if len(zero) > a.limit:
            print(f"  … 其余 {len(zero) - a.limit} 条")
    return 0


if __name__ == '__main__':
    sys.exit(main())

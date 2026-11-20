#!/usr/bin/env python3
"""sp_pending · 交接标记 CLI（核心逻辑在 ssotlib.pending）

用法:
  sp_pending.py --status
  sp_pending.py --merge --sessions 12 --est-blocks 8000 --by-session abc
  sp_pending.py --decide --json
  sp_pending.py --mark-pack-stale
  sp_pending.py --clear-if-settled
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ssotlib import pending  # noqa: E402
from ssotlib import cli  # noqa: E402


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_pending.py --decide --json', root=False)
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--sessions', type=int, default=0)
    ap.add_argument('--est-blocks', type=int, default=0)
    ap.add_argument('--by-session')
    ap.add_argument('--mark-pack-stale', action='store_true')
    ap.add_argument('--clear-if-settled', action='store_true')
    ap.add_argument('--decide', action='store_true')
    ap.add_argument('--threshold', type=int)
    ap.add_argument('--window')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.merge:
        d = pending.merge(a.sessions, a.est_blocks, a.by_session)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else f"pending: sessions={d['sessions']} est_blocks={d['est_blocks']}")
        return 0
    if a.mark_pack_stale:
        d = pending.mark_pack_stale()
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else 'pending: pack_stale=true')
        return 0
    if a.clear_if_settled:
        ok = pending.clear_if_settled()
        print(json.dumps({'cleared': ok}, ensure_ascii=False) if a.json else ('cleared' if ok else 'kept'))
        return 0
    if a.decide:
        d = pending.decide(a.threshold, a.window, a.force)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else
              f"action={d['action']} reason={d['reason']} pending={d.get('pending_blocks')}")
        return 0
    d = pending.load()
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    elif d:
        print(f"pending: {d.get('sessions', 0)} 会话 / ~{d.get('est_blocks', 0)} 块 "
              f"· since {d.get('created_at', '-')} · generation {d.get('generation', 0)}")
    else:
        print('pending: 无')
    return 0


if __name__ == '__main__':
    sys.exit(main())

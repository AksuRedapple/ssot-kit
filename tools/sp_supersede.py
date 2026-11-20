#!/usr/bin/env python3
"""sp_supersede · 断言取代提案/确认（append-only）

P2 phase 2 最小实现：
  - propose：写 knowledge/supersede-events.jsonl（不改正本）
  - confirm：写 assertions.meta.json（status=superseded, superseded_by=...）
  - from-conflict：列出 candidates.jsonl 里的 conflict，供人工指定 by

用法:
  python3 tools/sp_supersede.py --from-conflict
  python3 tools/sp_supersede.py --propose A012 --by A031 --reason "旧路径" --apply
  python3 tools/sp_supersede.py --confirm A012 --by A031 --reason "确认" --apply
  python3 tools/sp_supersede.py --list
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_assert_meta  # noqa: E402
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
CAND = os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')
EVENTS = os.path.join(SSOT, 'knowledge', 'supersede-events.jsonl')


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def append(e):
    os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
    with open(EVENTS, 'a', encoding='utf-8') as f:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')


def list_events(as_json=False):
    rows = []
    try:
        for line in open(EVENTS, encoding='utf-8', errors='replace'):
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    except OSError:
        pass
    if as_json:
        print(json.dumps({'count': len(rows), 'events': rows}, ensure_ascii=False, indent=1))
    else:
        print(f"events: {len(rows)}")
        for e in rows[-20:]:
            print(f"  {e.get('ts')} {e.get('op')} {e.get('id')} → {e.get('superseded_by') or '-'}  {e.get('reason') or ''}")
    return 0


def from_conflict(as_json=False):
    out = []
    try:
        for line in open(CAND, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('state') == 'conflict' and d.get('assertion'):
                out.append({'candidate': d.get('id'), 'claim': d.get('claim'),
                            'assertion': d.get('assertion'), 'score': d.get('assertion_score')})
    except OSError:
        pass
    if as_json:
        print(json.dumps({'count': len(out), 'conflicts': out}, ensure_ascii=False, indent=1))
    else:
        print(f"conflicts: {len(out)}（需要人工指定 --by 后再 --propose）")
        for x in out:
            print(f"  {x['assertion']} ← {x['candidate']} {str(x['claim'])[:80]}")
    return 0 if out else 1


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_supersede.py --propose A012 --by A031 --apply', root=False)
    ap.add_argument('--propose')
    ap.add_argument('--confirm')
    ap.add_argument('--by')
    ap.add_argument('--reason', default='manual')
    ap.add_argument('--operator', default=os.environ.get('USER', '-'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--from-conflict', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.list:
        return list_events(a.json)
    if a.from_conflict:
        return from_conflict(a.json)
    if a.propose:
        if not a.by:
            print('--propose 需要 --by', file=sys.stderr); return 2
        e = {'ts': now(), 'op': 'propose', 'id': a.propose, 'superseded_by': a.by,
             'reason': a.reason, 'operator': a.operator}
        if a.apply:
            append(e)
            print(f"✅ propose {a.propose} → {a.by}（已写 {EVENTS}）")
        else:
            print(f"DRY propose {a.propose} → {a.by}（加 --apply 写入）")
        return 0
    if a.confirm:
        if not a.by:
            print('--confirm 需要 --by', file=sys.stderr); return 2
        if not a.apply:
            print(f"DRY confirm {a.confirm} → {a.by}")
            return 0
        # set_one 自己会写一条 op=set 事件，不再重复 append
        return sp_assert_meta.set_one(a.confirm, 'superseded', a.by, a.reason, a.operator)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())

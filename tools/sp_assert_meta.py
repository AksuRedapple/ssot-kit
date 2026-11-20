#!/usr/bin/env python3
"""sp_assert_meta · 断言机器状态层（knowledge/assertions.meta.json）

不重写 assertions.md：机器状态放 sidecar，索引读 sidecar。
状态：active / superseded / refuted / vacant / unknown。

用法:
  python3 tools/sp_assert_meta.py --scan
  python3 tools/sp_assert_meta.py --apply
  python3 tools/sp_assert_meta.py --set A012 --status superseded --by A031 --reason "..."
  python3 tools/sp_assert_meta.py --json
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib.asserts import CITE_RX, parse  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
ASSERT = os.path.join(SSOT, 'knowledge', 'assertions.md')
META = os.path.join(SSOT, 'knowledge', 'assertions.meta.json')
EVENTS = os.path.join(SSOT, 'knowledge', 'supersede-events.jsonl')


def load_meta():
    try:
        return json.load(open(META, encoding='utf-8'))
    except Exception:
        return {'schema': 1, 'entries': {}}


def save_meta(d):
    os.makedirs(os.path.dirname(META), exist_ok=True)
    tmp = META + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, META)


def log_event(e):
    try:
        os.makedirs(os.path.dirname(EVENTS), exist_ok=True)
        with open(EVENTS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    except Exception:
        pass


def scan(as_json=False):
    blocks = parse(ASSERT)
    old = load_meta().get('entries') or {}
    entries, changed = {}, 0
    for b in blocks:
        prev = old.get(b['id']) or {}
        status = prev.get('status') if prev.get('source') == 'manual' else b['status']
        sup = prev.get('superseded_by') if prev.get('source') == 'manual' else (b['superseded_by'] or prev.get('superseded_by'))
        entry = {
            'status': status or 'unknown',
            'superseded_by': sup or None,
            'title': b['title'],
            'line': b['line'],
            'tags': b['tags'],
            'source': prev.get('source') or 'prose',
        }
        for k in ('scope', 'confirmed_by', 'note'):
            if prev.get(k):
                entry[k] = prev[k]
        entries[b['id']] = entry
        if prev.get('status') != entry['status'] or prev.get('superseded_by') != entry['superseded_by']:
            changed += 1
    out = {'schema': 1,
           'generated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
           'entries': entries}
    if as_json:
        print(json.dumps({'total': len(entries), 'changed': changed,
                          'status_counts': _counts(entries), 'entries': entries},
                         ensure_ascii=False, indent=1))
    else:
        print(f"assertions: {len(entries)} · 变更 {changed}")
        print("status: " + ' / '.join(f'{k} {v}' for k, v in _counts(entries).items()))
    return out, changed


def _counts(entries):
    c = {}
    for e in entries.values():
        c[e.get('status', 'unknown')] = c.get(e.get('status', 'unknown'), 0) + 1
    return dict(sorted(c.items()))


def set_one(aid, status, by, reason, operator):
    blocks = {b['id']: b for b in parse(ASSERT)}
    if aid not in blocks:
        print(f"未知断言 {aid}", file=sys.stderr)
        return 2
    if by and by not in blocks:
        print(f"superseded_by 目标不存在 {by}", file=sys.stderr)
        return 2
    d = load_meta()
    entries = d.setdefault('entries', {})
    e = entries.setdefault(aid, {})
    e.update({'status': status, 'superseded_by': by or None,
              'title': blocks[aid]['title'], 'line': blocks[aid]['line'],
              'tags': blocks[aid]['tags'], 'source': 'manual',
              'confirmed_by': operator, 'note': reason})
    d['generated_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    save_meta(d)
    log_event({'ts': d['generated_at'], 'op': 'set', 'id': aid, 'status': status,
               'superseded_by': by, 'reason': reason, 'operator': operator})
    print(f"✅ {aid} status={status}" + (f" superseded_by={by}" if by else ''))
    return 0


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_assert_meta.py --apply',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--set', metavar='AID')
    ap.add_argument('--status')
    ap.add_argument('--by')
    ap.add_argument('--reason', default='manual')
    ap.add_argument('--operator', default=os.environ.get('USER', '-'))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.set:
        if not a.status:
            print('--set 需要 --status', file=sys.stderr); return 2
        return set_one(a.set, a.status, a.by, a.reason, a.operator)
    out, changed = scan(a.json)
    if a.apply:
        save_meta(out)
        print(f"✅ 写 {META}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

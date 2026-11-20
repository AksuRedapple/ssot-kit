#!/usr/bin/env python3
"""sp_classify · 给 S1 会话打 session_class（backfill / 规则扫描 / 手工覆盖）

只写 S1 的 meta.json（原子替换），不动 transcript/S0；每次写都进
logs/classify-ops.jsonl（old/new/reason/source），可审计。

用法:
  python3 tools/sp_classify.py --scan                 # 只读预览
  python3 tools/sp_classify.py --apply                # 按 policy 规则写入
  python3 tools/sp_classify.py --set 1a2b3c4d --class monitor --reason "钉钉值守"
  python3 tools/sp_classify.py --init                 # 建 profile/index-policy.json
  python3 tools/sp_classify.py --scan --json
"""
import argparse
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import policy as sp_policy  # noqa: E402
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
LOG = os.path.join(SSOT, 'logs', 'classify-ops.jsonl')


def metas(only_harness=None):
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions'))):
        harness = os.path.basename(os.path.dirname(top))
        if only_harness and harness != only_harness:
            continue
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            mp = os.path.join(d, 'meta.json')
            if not os.path.isfile(mp):
                continue
            try:
                meta = json.load(open(mp, encoding='utf-8'))
            except Exception:
                continue
            rel = os.path.relpath(d, SSOT)
            yield harness, d, mp, rel, meta


def write_meta(mp, meta):
    tmp = mp + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, mp)


def log_op(rec):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        os.chmod(LOG, 0o600)
    except Exception:
        pass


def init_policy():
    p = os.path.join(SSOT, sp_policy.POLICY_REL)
    if os.path.exists(p):
        print(f'已存在: {p}')
        return 0
    os.makedirs(os.path.dirname(p), exist_ok=True)
    d = {'schema': 1, 'enabled': True,
         'include': ['human', 'decision', 'unknown'],
         'skip': ['automation', 'monitor'],
         'rules': [],
         'heuristics': False}
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'✅ 已建 {p}（未配规则；所有会话默认 human，不会跳过任何东西）')
    return 0


def scan(apply=False, only=None, as_json=False, heuristic=None):
    policy = sp_policy.load_policy(SSOT)
    if heuristic is not None:
        policy['heuristics'] = bool(heuristic)
    rows, changed = [], 0
    for harness, d, mp, rel, meta in metas(only):
        old = sp_policy.class_of(meta)
        cls, reason, source = sp_policy.suggest_class(meta, rel, policy)
        changed_here = cls != old or meta.get('class_reason') != reason
        if changed_here:
            changed += 1
        rows.append({'sid': sp_policy.sid_of(meta, rel), 'harness': harness,
                     'path': rel, 'old': old, 'class': cls,
                     'source': source, 'reason': reason,
                     'title': (meta.get('title') or '')[:40], 'changed': changed_here})
        if apply and changed_here:
            old_rec = {k: meta.get(k) for k in
                       ('session_class', 'class_reason', 'class_source', 'classified_at')}
            meta['session_class'] = cls
            meta['class_reason'] = reason
            meta['class_source'] = source
            meta['classified_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            write_meta(mp, meta)
            log_op({'ts': meta['classified_at'], 'op': 'classify', 'sid': sp_policy.sid_of(meta, rel),
                    'path': rel, 'class': cls, 'source': source, 'reason': reason,
                    'old': old_rec})
    if as_json:
        print(json.dumps({'policy': policy, 'total': len(rows), 'changed': changed,
                          'rows': rows}, ensure_ascii=False, indent=1))
    else:
        print(f"policy: {sp_policy.summary(policy)}")
        print(f"{'SID':10s}{' harness':9s}{' old':11s}{' class':11s}{' source':9s}  title")
        for r in rows[:200]:
            mark = '*' if r['changed'] else ' '
            print(f"{mark}{r['sid'][:8]:9s} {r['harness']:8s} {r['old']:10s} {r['class']:10s} {r['source']:8s}  {r['title']}")
        if len(rows) > 200:
            print(f"… 其余 {len(rows) - 200} 条")
        print(f"\n共 {len(rows)} 个 S1；将变更 {changed} 个" + ('（已写入）' if apply else '（预览；加 --apply 写入）'))
    return 0


def set_one(sid8, cls, reason):
    cls = cls.lower()
    if cls not in sp_policy.CLASSES:
        print(f"未知 class: {cls}（可选 {','.join(sp_policy.CLASSES)}）", file=sys.stderr)
        return 2
    hits = []
    for harness, d, mp, rel, meta in metas():
        if sp_policy.sid_of(meta, rel).startswith(sid8):
            hits.append((d, mp, rel, meta))
    if len(hits) != 1:
        print(f"找到 {len(hits)} 个 S1；需要唯一 sid 前缀", file=sys.stderr)
        return 2
    d, mp, rel, meta = hits[0]
    old = meta.get('session_class')
    meta['session_class'] = cls
    meta['class_reason'] = reason or 'manual'
    meta['class_source'] = 'manual'
    meta['classified_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    write_meta(mp, meta)
    log_op({'ts': meta['classified_at'], 'op': 'classify', 'sid': sp_policy.sid_of(meta, rel),
            'path': rel, 'class': cls, 'source': 'manual', 'reason': reason or 'manual',
            'old': {'session_class': old}})
    print(f"✅ {sp_policy.sid_of(meta, rel)[:8]} → {cls}（{reason or 'manual'}）")
    return 0


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_classify.py --scan\n  sp_classify.py --apply', root=False)
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--set', metavar='SID8')
    ap.add_argument('--class', dest='cls')
    ap.add_argument('--reason')
    ap.add_argument('--harness')
    ap.add_argument('--heuristic', action='store_true', default=None)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.init:
        return init_policy()
    if a.set:
        if not a.cls:
            print('--set 需要 --class', file=sys.stderr); return 2
        return set_one(a.set, a.cls, a.reason)
    return scan(apply=a.apply, only=a.harness, as_json=a.json, heuristic=a.heuristic)


if __name__ == '__main__':
    sys.exit(main())

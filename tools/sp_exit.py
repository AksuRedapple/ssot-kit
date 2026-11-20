#!/usr/bin/env python3
"""sp_exit · 索引退出（stable sid + tombstone + 验收 + 审计）

边界：退出只删**索引块 + src_state**；S0/S1 保留。tombstone 写
profile/retired.jsonl（追加式），sp_index 永久跳过，除非 --include-retired。

用法:
  python3 tools/sp_exit.py --make-manifest --sid 1a2b3c4d --out logs/exit.jsonl
  python3 tools/sp_exit.py --make-manifest --class automation,monitor --out logs/exit.jsonl
  python3 tools/sp_exit.py --retire logs/exit.jsonl --reason "44 个值守会话" --apply
  python3 tools/sp_exit.py --verify logs/exit.jsonl
  python3 tools/sp_exit.py --list
  python3 tools/sp_exit.py --unretire 1a2b3c4d --apply
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import policy as sp_policy  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
SEM = os.path.join(SSOT, 'S2-index', 'semantic')
OPS = os.path.join(SSOT, 'logs', 'index-ops.jsonl')


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def active_version():
    try:
        v = json.load(open(os.path.join(SEM, 'active.json'), encoding='utf-8')).get('version')
        if v and os.path.exists(os.path.join(SEM, 'versions', v, 'index.db')):
            return v
    except Exception:
        pass
    return None


def resolve_db():
    v = active_version()
    return os.path.join(SEM, 'versions', v, 'index.db') if v else os.path.join(SEM, 'index.db')


def all_s1(only_class=None):
    out = []
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions'))):
        harness = os.path.basename(os.path.dirname(top))
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            mp = os.path.join(d, 'meta.json')
            if not os.path.isfile(mp):
                continue
            try:
                meta = json.load(open(mp, encoding='utf-8'))
            except Exception:
                continue
            rel = os.path.relpath(d, SSOT)
            cls = sp_policy.class_of(meta)
            if only_class and cls not in only_class:
                continue
            out.append({'sid': sp_policy.sid_of(meta, rel), 'harness': harness,
                        'dir': d, 'rel': rel, 'meta': meta, 'class': cls})
    return out


def find_sids(prefixes):
    items = all_s1()
    out = []
    for p in prefixes:
        hits = [x for x in items if x['sid'].startswith(p)]
        if len(hits) != 1:
            print(f"⚠️ {p}: 命中 {len(hits)} 个 S1（需要唯一）", file=sys.stderr)
            continue
        out.append(hits[0])
    return out


def chunk_count(con, rel, sid=None):
    if rel == '-':
        return 0
    p = os.path.join(rel, 'transcript.jsonl')
    q, args = 'select count(*) from chunks where path=?', [p]
    if sid:
        # 标题变化会换 S1 目录；sid8 是稳定锚，路径只作辅助
        q += ' or path like ?'
        args.append('%' + str(sid)[:8] + '%')
    return con.execute(q, args).fetchone()[0]


def delete_source(con, rel, sid=None):
    p = os.path.join(rel, 'transcript.jsonl')
    con.execute('delete from chunks where path=?', (p,))
    con.execute('delete from src_state where path=?', (p,))
    if sid:
        con.execute('delete from chunks where path like ?', ('%' + str(sid)[:8] + '%',))
        con.execute('delete from src_state where path like ?', ('%' + str(sid)[:8] + '%',))


def sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
    except OSError:
        return '-'
    return h.hexdigest()


def write_manifest(items, out, reason, operator):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    db = resolve_db()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True) if os.path.exists(db) else None
    lines = [{'schema': 1, 'kind': 'exit-manifest', 'created_at': now(),
              'operator': operator, 'reason': reason}]
    for x in items:
        blocks = chunk_count(con, x['rel'], x['sid']) if con else 0
        lines.append({'sid': x['sid'], 'harness': x['harness'], 'path': x['rel'],
                      'class': x['class'], 'blocks': blocks,
                      'sha256': sha256(os.path.join(x['dir'], 'transcript.jsonl')),
                      'reason': reason, 'operator': operator, 'ts': now()})
    if con:
        con.close()
    with open(out, 'w', encoding='utf-8') as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f"✅ 清单 {out}（{len(items)} 个会话，{sum(x.get('blocks', 0) for x in lines[1:])} 块）")
    return 0


def read_manifest(path):
    out = []
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('kind') == 'exit-manifest':
            continue
        if d.get('sid'):
            out.append(d)
    return out


def append_retired(event):
    p = os.path.join(SSOT, sp_policy.RETIRED_REL)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')


def touch_build(db):
    """退出后刷新 BUILD 读数（chunks/retired/db_bytes），不重建索引。"""
    if not os.path.exists(db):
        return
    try:
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        n = con.execute('select count(*) from chunks').fetchone()[0]
        con.close()
    except Exception:
        return
    retired, _ = sp_policy.load_retired(SSOT)
    paths = [os.path.join(os.path.dirname(db), 'BUILD.json'),
             os.path.join(SEM, 'BUILD.json')]
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding='utf-8'))
            d['chunks'] = n
            d['built_at'] = now()
            d.setdefault('policy', {})['retired_sources'] = len(retired)
            d['db_bytes'] = os.path.getsize(db)
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
                f.write('\n')
            os.replace(tmp, p)
        except Exception:
            pass


def log_op(rec):
    try:
        os.makedirs(os.path.dirname(OPS), exist_ok=True)
        with open(OPS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        os.chmod(OPS, 0o600)
    except Exception:
        pass


def retire(manifest, sids, reason, operator, apply=False, as_json=False):
    items = read_manifest(manifest) if manifest else find_sids(sids or [])
    if not items:
        print('没有可退出的会话', file=sys.stderr)
        return 2
    db = resolve_db()
    con = sqlite3.connect(db, timeout=30) if os.path.exists(db) else None
    retired, _ = sp_policy.load_retired(SSOT)
    rows = []
    for x in items:
        sid, rel = x['sid'], x.get('path') or '-'
        already = sid in retired
        before = chunk_count(con, rel, sid) if con else 0
        rows.append({'sid': sid, 'path': rel, 'already_retired': already, 'blocks_before': before})
        if not apply:
            continue
        if already:
            # 重跑/半途中断：tombstone 已在，但块可能没删干净 → 修复删除，不重复追加事件
            if con and rel != '-' and before:
                delete_source(con, rel, sid)
                con.commit()
                after = chunk_count(con, rel, sid)
                log_op({'ts': now(), 'op': 'retire-repair', 'sid': sid,
                        'harness': x.get('harness'), 'path': rel,
                        'blocks_before': before, 'blocks_after': after,
                        'version': active_version(), 'db': db, 'operator': operator,
                        'reason': reason, 'manifest': os.path.basename(manifest) if manifest else None})
                rows[-1]['blocks_after'] = after
            continue
        append_retired({'ts': now(), 'op': 'retire', 'sid': sid,
                        'harness': x.get('harness'), 'path': rel,
                        'reason': reason, 'operator': operator,
                        'manifest': os.path.basename(manifest) if manifest else None})
        if con and rel != '-':
            delete_source(con, rel, sid)
            con.commit()
        after = chunk_count(con, rel, sid) if con else 0
        log_op({'ts': now(), 'op': 'retire', 'sid': sid, 'harness': x.get('harness'),
                'path': rel, 'blocks_before': before, 'blocks_after': after,
                'version': active_version(), 'db': db, 'operator': operator,
                'reason': reason, 'manifest': os.path.basename(manifest) if manifest else None})
        rows[-1]['blocks_after'] = after
    if con:
        con.close()
    if apply:
        touch_build(db)
    if as_json:
        print(json.dumps({'apply': apply, 'rows': rows}, ensure_ascii=False, indent=1))
    else:
        print(('APPLY' if apply else 'DRY-RUN') + f" · {len(rows)} 个会话")
        for r in rows:
            print(f"  {r['sid'][:8]}  {r['path']}  blocks={r['blocks_before']}"
                  + ('  (已退休)' if r['already_retired'] else ''))
        if not apply:
            print('  （未写入；确认后加 --apply）')
    return 0


def verify(manifest, as_json=False):
    items = read_manifest(manifest)
    db = resolve_db()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True) if os.path.exists(db) else None
    retired, _ = sp_policy.load_retired(SSOT)
    rows, bad = [], 0
    for x in items:
        sid, rel = x['sid'], x.get('path') or '-'
        n = chunk_count(con, rel, sid) if con else 0
        ok = (n == 0) and (sid in retired)
        bad += 0 if ok else 1
        rows.append({'sid': sid, 'path': rel, 'blocks': n, 'retired': sid in retired, 'ok': ok})
    if con:
        con.close()
    if as_json:
        print(json.dumps({'manifest': manifest, 'pass': bad == 0, 'rows': rows},
                         ensure_ascii=False, indent=1))
    else:
        print(f"verify {manifest}: {'PASS' if bad == 0 else 'FAIL'}（{len(rows)} 个，失败 {bad}）")
        for r in rows:
            print(f"  {'ok  ' if r['ok'] else 'FAIL'} {r['sid'][:8]} blocks={r['blocks']} "
                  f"retired={r['retired']} {r['path']}")
    return 0 if bad == 0 else 1


def list_retired(as_json=False):
    retired, state = sp_policy.load_retired(SSOT)
    rows = [state[s] for s in sorted(retired)]
    if as_json:
        print(json.dumps({'count': len(rows), 'rows': rows}, ensure_ascii=False, indent=1))
    else:
        print(f"retired: {len(rows)}")
        for r in rows:
            print(f"  {str(r.get('sid'))[:8]}  {r.get('harness') or '-'}  "
                  f"{r.get('path') or '-'}  {r.get('reason') or '-'}")
    return 0


def unretire(sids, apply=False):
    items = find_sids(sids)
    if not items:
        return 2
    for x in items:
        if not apply:
            print(f"DRY: 将解除 {x['sid'][:8]}（{x['rel']}）")
            continue
        append_retired({'ts': now(), 'op': 'unretire', 'sid': x['sid'],
                        'harness': x['harness'], 'path': x['rel'],
                        'reason': 'manual unretire', 'operator': os.environ.get('USER', '-')})
        log_op({'ts': now(), 'op': 'unretire', 'sid': x['sid'], 'path': x['rel'],
                'version': active_version(), 'db': resolve_db(),
                'operator': os.environ.get('USER', '-'), 'reason': 'manual unretire'})
        print(f"✅ 已解除 {x['sid'][:8]}（下次 sp_index --incremental 重新入索引）")
    if not apply:
        print('  （未写入；确认后加 --apply）')
    return 0


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_exit.py --make-manifest --class monitor --out logs/exit.jsonl',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--make-manifest', action='store_true')
    ap.add_argument('--retire', metavar='MANIFEST')
    ap.add_argument('--verify', metavar='MANIFEST')
    ap.add_argument('--unretire', nargs='+', metavar='SID')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--sid', action='append', default=[], help='可重复/逗号分隔')
    ap.add_argument('--class', dest='cls')
    ap.add_argument('--out')
    ap.add_argument('--reason', default='manual exit')
    ap.add_argument('--operator', default=os.environ.get('USER', '-'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    sids = []
    for s in a.sid:
        sids += [x.strip() for x in s.split(',') if x.strip()]

    if a.make_manifest:
        if sids:
            items = find_sids(sids)
        elif a.cls:
            items = all_s1(set(x.strip() for x in a.cls.split(',') if x.strip()))
        else:
            print('--make-manifest 需要 --sid 或 --class', file=sys.stderr); return 2
        out = a.out or os.path.join(SSOT, 'logs', f'exit-manifest-{datetime.datetime.now():%Y%m%d-%H%M%S}.jsonl')
        return write_manifest(items, out, a.reason, a.operator)
    if a.retire:
        return retire(a.retire, None, a.reason, a.operator, a.apply, a.json)
    if a.verify:
        return verify(a.verify, a.json)
    if a.unretire:
        return unretire(a.unretire, a.apply)
    if a.list:
        return list_retired(a.json)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())

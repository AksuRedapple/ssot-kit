#!/usr/bin/env python3
"""sp_s0scan · S0 归档密钥形态巡检（只报文件数/路径，不打印内容）

背景：S1 脱敏 + 索引隐私闸只能证明“派生层/索引”干净，不能证明 S0 原文干净。
用法:
  python3 tools/sp_s0scan.py                 # 表
  python3 tools/sp_s0scan.py --json          # 机读
  python3 tools/sp_s0scan.py --write-state   # 写 alerts/s0-scan.json（供 ssot_check）
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import secrets  # noqa: E402
from ssotlib.ingest import SECRET_RX  # noqa: E402  (兼容旧测试/调用方)
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
STATE = os.path.join(SSOT, 'alerts', 's0-scan.json')
EXTS = ('.jsonl', '.json', '.md', '.txt')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
MAX_BYTES = 256 * 1024 * 1024


def _harness(path):
    parts = path.split(os.sep)
    try:
        return parts[parts.index('evidence') + 1]
    except (ValueError, IndexError):
        return '?'


def scan(only=None, unique=False):
    root = os.path.join(SSOT, 'evidence')
    files = hits = matches = skipped = 0
    by_conf = {'high': 0, 'medium': 0, 'low': 0}
    high_files = 0
    sample = []
    uniq = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        parts = dirpath.split(os.sep)
        if 'S0-archive' not in parts:
            continue
        if only:
            h = _harness(dirpath)
            if h not in only:
                continue
        for fn in filenames:
            if not fn.endswith(EXTS):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    skipped += 1
                    continue
                text = open(p, encoding='utf-8', errors='replace').read()
            except OSError:
                skipped += 1
                continue
            files += 1
            ms = secrets.classify(text)
            if not ms:
                continue
            hits += 1
            matches += len(ms)
            rel = os.path.relpath(p, SSOT)
            confs = [m['confidence'] for m in ms]
            if 'high' in confs:
                high_files += 1
            for c in confs:
                by_conf[c] += 1
            if len(sample) < 20:
                sample.append(rel)
            if unique:
                harn = _harness(dirpath)
                for m in ms:
                    h = secrets.hash8(m['value'])
                    rec = uniq.setdefault(h, {
                        'hash': h, 'prefix': m['value'][:6] + '…',
                        'len': len(m['value']), 'kind': m['kind'],
                        'confidence': m['confidence'], 'count': 0,
                        'files': set(), 'harness': set(), 'first': rel})
                    rec['count'] += 1
                    rec['files'].add(rel)
                    rec['harness'].add(harn)
                    rank = {'low': 0, 'medium': 1, 'high': 2}
                    if rank[m['confidence']] > rank[rec['confidence']]:
                        rec['confidence'] = m['confidence']
    out = {'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
           'scanned': files, 'files_hit': hits, 'matches': matches,
           'high_files': high_files, 'by_confidence': by_conf,
           'skipped': skipped, 'sample': sample}
    if unique:
        rows = []
        for rec in uniq.values():
            rec['files'] = len(rec['files'])
            rec['harness'] = ','.join(sorted(rec['harness']))
            rows.append(rec)
        rows.sort(key=lambda x: -x['count'])
        out['unique_count'] = len(rows)
        out['unique'] = rows
    return out

def main():
    ap = cli.base_parser(epilog='示例:\n  sp_s0scan.py --write-state', root=False)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--write-state', action='store_true')
    ap.add_argument('--only', help='逗号分隔的 harness（如 pi,cc）；只扫这些源')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--unique', action='store_true',
                    help='按值 sha256 聚合（脱敏前缀 + 次数 + 文件数 + 置信度）')
    a = ap.parse_args()
    only = set(x.strip() for x in a.only.split(',')) if a.only else None
    d = scan(only, unique=a.unique)
    if a.write_state:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, STATE)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    elif not a.quiet:
        c = d['by_confidence']
        print(f"S0 secrets: {d['files_hit']}/{d['scanned']} 文件命中 · {d['matches']} 处"
              f"（high {c['high']} / medium {c['medium']} / low {c['low']}）"
              + (f" · 跳过 {d['skipped']}" if d['skipped'] else ''))
        if a.unique:
            print(f"唯一值 {d.get('unique_count', 0)} 个（按出现次数）:")
            for r in (d.get('unique') or [])[:20]:
                print(f"  {r['count']:5d}× {r['prefix']} len={r['len']} "
                      f"{r['confidence']}/{r['kind']} {r['harness']} files={r['files']} {r['first']}")
        else:
            for p in d['sample']:
                print(f"  - {p}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

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
from ssotlib.ingest import SECRET_RX  # noqa: E402
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
STATE = os.path.join(SSOT, 'alerts', 's0-scan.json')
EXTS = ('.jsonl', '.json', '.md', '.txt')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
MAX_BYTES = 256 * 1024 * 1024


def scan(only=None):
    root = os.path.join(SSOT, 'evidence')
    files = hits = matches = skipped = 0
    sample = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        parts = dirpath.split(os.sep)
        if 'S0-archive' not in parts:
            continue
        if only:
            try:
                h = parts[parts.index('evidence') + 1]
            except Exception:
                h = ''
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
            n = sum(len(rx.findall(text)) for rx, _rep in SECRET_RX)
            if n:
                hits += 1
                matches += n
                if len(sample) < 20:
                    sample.append(os.path.relpath(p, SSOT))
    return {'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'scanned': files, 'files_hit': hits, 'matches': matches,
            'skipped': skipped, 'sample': sample}


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_s0scan.py --write-state', root=False)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--write-state', action='store_true')
    ap.add_argument('--only', help='逗号分隔的 harness（如 pi,cc）；只扫这些源')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    only = set(x.strip() for x in a.only.split(',')) if a.only else None
    d = scan(only)
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
        print(f"S0 secrets: {d['files_hit']}/{d['scanned']} 文件命中 · {d['matches']} 处"
              + (f" · 跳过 {d['skipped']}" if d['skipped'] else ''))
        for p in d['sample']:
            print(f"  - {p}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""sp_sources · CLI（发现逻辑在 ssotlib.sources）

用法:
  python3 tools/sp_sources.py [--json] [--only qoder,cc] [--since 30d]
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ssotlib.sources import discover, parse_since  # noqa: E402
from ssotlib import cli  # noqa: E402


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_sources.py\n  sp_sources.py --json', root=False)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--only', help='逗号分隔：qoder,cc,dsh,pi,codex,opencode,qoder-app')
    ap.add_argument('--since', help='只统计最近变更，如 30d / 12h / 2w')
    a = ap.parse_args()
    only = set(a.only.split(',')) if a.only else None
    rows = discover(only, parse_since(a.since))
    if a.json:
        print(json.dumps({'sources': rows}, ensure_ascii=False, indent=1))
        return 0
    print(f"{'源':11s}{'角色':6s}{'方式':7s}{'会话':>7s}{'文件':>7s}{'字节':>12s}")
    for r in rows:
        print(f"{r['src']:11s}{r['role']:6s}{r['kind']:7s}{r['sessions']:7d}"
              f"{r['files']:7d}{r['bytes']:12d}")
        for root in r['roots']:
            print(f"  - {root['path']}" + (f" → {root['dest']}" if root['dest'] else ' （sqlite，由对应转换器处理）'))
    print('\n说明：sessions 是发现数（真源），不是 evidence/ 归档数；归档与转换是下一步。')
    return 0


if __name__ == '__main__':
    sys.exit(main())

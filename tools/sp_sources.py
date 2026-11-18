#!/usr/bin/env python3
"""sp_sources · 会话源发现层（只读）：harness 真源 → 结构化清单

为什么单独一层：覆盖审计不能拿 evidence/ 自己的归档当分母（循环自证）；
sp_archive / sp_recall 也需要同一份“真源在哪”的答案。

用法:
  python3 tools/sp_sources.py                 # 表
  python3 tools/sp_sources.py --json          # 机读
  python3 tools/sp_sources.py --only qoder,cc --since 30d

数据源可用环境变量覆盖（测试/外置盘）：
  SSOT_QODER_ROOT / SSOT_QODERWORK_ROOT / SSOT_CC_ROOT / SSOT_DSH_ROOT / SSOT_PI_ROOT /
  SSOT_CODEX_ROOT / SSOT_OPENCODE_DB / SSOT_QODER_APP_DB
多个根用 os.pathsep 分隔。
"""
import argparse
import datetime
import glob
import json
import os
import sqlite3
import sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
HOME = os.path.expanduser('~')

# (src, role, 归档方式, [(真源根, 归档相对目录), ...])
ROOTS = [
    ('qoder', 'human', 'jsonl', [
        (os.environ.get('SSOT_QODER_ROOT', os.path.join(HOME, '.qoder', 'projects')),
         'evidence/qoder/S0-archive/qoder-projects'),
        (os.environ.get('SSOT_QODERWORK_ROOT', os.path.join(HOME, '.qoderwork', 'projects')),
         'evidence/qoder/S0-archive/qoder-projects'),
    ]),
    ('cc', 'human', 'jsonl', [
        (os.environ.get('SSOT_CC_ROOT', os.path.join(HOME, '.claude', 'projects')),
         'evidence/cc/S0-archive/claude-projects'),
    ]),
    ('dsh', 'human', 'jsonl', [
        (os.environ.get('SSOT_DSH_ROOT', os.path.join(HOME, '.dsh', 'sessions')),
         'evidence/dsh/S0-archive/dsh-sessions'),
    ]),
    ('pi', 'human', 'jsonl', [
        (os.environ.get('SSOT_PI_ROOT', os.path.join(HOME, '.pi', 'agent', 'sessions')),
         'evidence/pi/S0-archive/pi-sessions'),
    ]),
    ('codex', 'tool', 'jsonl', [
        (os.environ.get('SSOT_CODEX_ROOT', os.path.join(HOME, '.codex', 'sessions')),
         'evidence/codex/S0-archive/codex-sessions'),
    ]),
]

SQLITE = [
    ('qoder-app', 'human', os.environ.get(
        'SSOT_QODER_APP_DB',
        os.path.join(HOME, 'Library', 'Application Support', 'com.qoder.app.stable', 'main.sqlite'))),
    ('opencode', 'human', os.environ.get(
        'SSOT_OPENCODE_DB', os.path.join(HOME, '.local', 'share', 'opencode', 'opencode.db'))),
]


def parse_since(s):
    if not s:
        return None
    unit = s[-1]
    try:
        n = float(s[:-1])
    except ValueError:
        return None
    hours = {'h': 1, 'd': 24, 'w': 24 * 7}[unit] * n
    return datetime.datetime.now().timestamp() - hours * 3600


def count_sessions(kind, root):
    if kind == 'dsh':
        return len(glob.glob(os.path.join(root, '*', '*', 'session.v4.jsonl.zstd')))
    if kind == 'codex':
        return len(glob.glob(os.path.join(root, '**', '*.jsonl'), recursive=True))
    return len(glob.glob(os.path.join(root, '*', '*.jsonl')))


def walk_stats(root, since=None):
    files = 0
    nbytes = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ('node_modules', '__pycache__', 'cache')]
        for fn in filenames:
            if fn in ('.DS_Store',) or fn.endswith(('.lock', '.tmp')):
                continue
            p = os.path.join(dirpath, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if since and st.st_mtime < since:
                continue
            files += 1
            nbytes += st.st_size
    return files, nbytes


def sqlite_count(path):
    if not os.path.exists(path):
        return 0
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
        if con.execute("select 1 from sqlite_master where type='table' and name='chat_sessions'").fetchone():
            n = con.execute('select count(*) from chat_sessions').fetchone()[0]
        elif con.execute("select 1 from sqlite_master where type='table' and name='session_v2'").fetchone():
            n = con.execute('select count(*) from session_v2 where parent_id is null').fetchone()[0]
        elif con.execute("select 1 from sqlite_master where type='table' and name='session'").fetchone():
            n = con.execute('select count(*) from session where parent_id is null').fetchone()[0]
        else:
            n = 0
        con.close()
        return n
    except Exception:
        return 0


def discover(only=None, since=None):
    rows = []
    for src, role, kind, roots in ROOTS:
        if only and src not in only:
            continue
        item = {'src': src, 'role': role, 'kind': kind, 'roots': [],
                'sessions': 0, 'files': 0, 'bytes': 0}
        for root, dest in roots:
            root = os.path.expanduser(root)
            if not os.path.isdir(root):
                continue
            sess = count_sessions(src if src in ('dsh', 'codex') else 'jsonl', root)
            files, nbytes = walk_stats(root, since)
            item['roots'].append({'path': root, 'dest': dest, 'sessions': sess,
                                  'files': files, 'bytes': nbytes})
            item['sessions'] += sess
            item['files'] += files
            item['bytes'] += nbytes
        if item['roots']:
            rows.append(item)
    for src, role, db in SQLITE:
        if only and src not in only:
            continue
        db = os.path.expanduser(db)
        if not os.path.exists(db):
            continue
        rows.append({'src': src, 'role': role, 'kind': 'sqlite', 'roots': [
            {'path': db, 'dest': None, 'sessions': sqlite_count(db), 'files': 1,
             'bytes': os.path.getsize(db)}],
            'sessions': sqlite_count(db), 'files': 1, 'bytes': os.path.getsize(db)})
    return rows


def iter_files(only=None, since=None):
    """→ [(src, path, size, mtime)]；只列可归档的 jsonl 根（dsh 的 zstd 也列）。"""
    for src, _role, kind, roots in ROOTS:
        if only and src not in only:
            continue
        for root, _dest in roots:
            root = os.path.expanduser(root)
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in ('node_modules', '__pycache__', 'cache')]
                for fn in filenames:
                    if fn in ('.DS_Store',) or fn.endswith(('.lock', '.tmp')):
                        continue
                    if not (fn.endswith('.jsonl') or fn.endswith('.jsonl.zstd')):
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    if since and st.st_mtime < since:
                        continue
                    yield src, p, st.st_size, st.st_mtime


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_sources.py\n  sp_sources.py --json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
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

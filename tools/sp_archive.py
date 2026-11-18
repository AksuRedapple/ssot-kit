#!/usr/bin/env python3
"""sp_archive · 会话真源 → evidence/ 的 S0 归档（opt-in，默认 dry-run）

纪律：
  - 不解析正文，只做镜像与清单；
  - 同卷优先 hardlink（0 字节占用，源被 harness 删除后归档仍活）；跨卷回退 copy；
  - 刚写过的文件默认跳过（--settle 5 秒），避免归档半截 JSONL；
  - 默认 **不写**，必须显式 --apply。

用法:
  python3 tools/sp_archive.py                       # 预览
  python3 tools/sp_archive.py --apply               # 归档（hardlink 优先）
  python3 tools/sp_archive.py --only cc --since 30d --apply
  python3 tools/sp_archive.py --copy --apply        # 强制实体复制（外置盘）
"""
import argparse
import datetime
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_sources  # noqa: E402

SSOT = sp_sources.SSOT
MANIFEST = os.path.join(SSOT, 'logs', 'archive-manifest.jsonl')
SKIP_DIRS = {'node_modules', '__pycache__', 'cache'}
SKIP_FILES = {'.DS_Store'}


def inside_evidence(path):
    ev = os.path.realpath(os.path.join(SSOT, 'evidence'))
    return os.path.realpath(path).startswith(ev + os.sep)


def iter_root_files(root, settle, since):
    now = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith(('.lock', '.tmp')):
                continue
            if not (fn.endswith('.jsonl') or fn.endswith('.jsonl.zstd')):
                continue
            p = os.path.join(dirpath, fn)
            if inside_evidence(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            if since and st.st_mtime < since:
                continue
            if settle and now - st.st_mtime < settle:
                yield p, st, 'settling'
                continue
            yield p, st, 'ready'


def classify(src, dst, hardlink):
    try:
        sst = os.stat(src)
    except OSError:
        return 'missing', None
    if not os.path.exists(dst):
        return 'new', sst
    try:
        dst_st = os.stat(dst)
    except OSError:
        return 'new', sst
    same_inode = sst.st_ino == dst_st.st_ino and sst.st_dev == dst_st.st_dev
    if hardlink and same_inode:
        return 'skip', sst
    if not hardlink and same_inode:
        # --copy：把既有 hardlink 重新落成实体副本
        return 'update', sst
    if sst.st_size == dst_st.st_size and int(sst.st_mtime) == int(dst_st.st_mtime):
        return 'skip', sst
    return 'update', sst


def apply_one(src, dst, hardlink):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.unlink(dst)
    if hardlink:
        try:
            os.link(src, dst)
            return 'link'
        except OSError:
            pass
    shutil.copy2(src, dst)
    return 'copy'


def main():
    ap = argparse.ArgumentParser(
        epilog='示例:\n  sp_archive.py\n  sp_archive.py --apply',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='真正写入（默认 dry-run）')
    ap.add_argument('--copy', action='store_true', help='强制实体复制，不 hardlink')
    ap.add_argument('--only', default='qoder,cc,dsh,pi',
                    help='逗号分隔的源（默认 qoder,cc,dsh,pi；codex 需显式）')
    ap.add_argument('--since', help='只归档最近变更，如 30d / 12h / 2w')
    ap.add_argument('--settle', type=int, default=5, help='跳过 N 秒内还在写的文件（默认 5）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    only = set(x.strip() for x in a.only.split(',') if x.strip())
    since = sp_sources.parse_since(a.since)
    hardlink = not a.copy

    stats = {'seen': 0, 'new': 0, 'update': 0, 'skip': 0, 'settling': 0,
             'link': 0, 'copy': 0, 'bytes_new': 0, 'roots': 0}
    records = []

    for src, role, kind, roots in sp_sources.ROOTS:
        if src not in only or kind != 'jsonl':
            continue
        for root, dest_rel in roots:
            root = os.path.expanduser(root)
            if not os.path.isdir(root):
                continue
            stats['roots'] += 1
            dest_root = os.path.join(SSOT, dest_rel)
            for p, st, state in iter_root_files(root, a.settle, since):
                stats['seen'] += 1
                rel = os.path.relpath(p, root)
                dst = os.path.join(dest_root, rel)
                if state == 'settling':
                    stats['settling'] += 1
                    continue
                action, sst = classify(p, dst, hardlink)
                if action in ('skip', 'missing'):
                    stats['skip'] += 1
                    continue
                stats[action] += 1
                mode = 'dry'
                if a.apply:
                    mode = apply_one(p, dst, hardlink)
                    stats[mode] += 1
                    stats['bytes_new'] += sst.st_size if sst else 0
                records.append({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                                'src': src, 'action': action, 'mode': mode,
                                'bytes': sst.st_size if sst else 0,
                                'src_path': p, 'dst_path': dst})

    if a.apply and records:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, 'a', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    summary = {'apply': a.apply, 'hardlink': hardlink, 'ts': time.time(), **stats}
    if a.json:
        print(json.dumps({'summary': summary, 'records': records[:50]}, ensure_ascii=False, indent=1))
    else:
        print(('APPLY' if a.apply else 'DRY-RUN') +
              f" · roots {stats['roots']} · 扫描 {stats['seen']} · 新增 {stats['new']}"
              f" · 更新 {stats['update']} · 跳过 {stats['skip']} · 写中 {stats['settling']}")
        if a.apply:
            print(f"  link {stats['link']} · copy {stats['copy']} · 新增字节 {stats['bytes_new']:,}")
        else:
            print('  （未写入；确认后加 --apply）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

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
  python3 tools/sp_archive.py --scrub --dry         # 预览：哪些 S0 文件含密钥形态
  python3 tools/sp_archive.py --scrub --apply       # 归档时脱敏（copy-on-write，源不动）
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sp_sources  # noqa: E402
from sp_convert import scrub as scrub_text, SECRET_RX  # noqa: E402

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


def load_state():
    """读 archive-manifest 最后一条 per-dst，用于判断 scrub 是否已做。"""
    out = {}
    try:
        for line in open(MANIFEST, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('dst_path'):
                out[d['dst_path']] = d
    except OSError:
        pass
    return out


def count_hits(path, limit_bytes=256 * 1024 * 1024):
    try:
        if os.path.getsize(path) > limit_bytes:
            return None
        data = open(path, 'rb').read()
    except OSError:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None
    return sum(len(rx.findall(text)) for rx, _rep in SECRET_RX)


def classify(src, dst, hardlink, scrub=False, prev=None, rescan=False):
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
    if scrub:
        p = (prev or {}).get(dst) or {}
        if (not rescan and p.get('scrubbed') and
                int(p.get('src_mtime') or 0) == int(sst.st_mtime) and
                int(p.get('bytes') or -1) == sst.st_size):
            return 'skip', sst
        # 首次 scrub：即使 dest 与源同 inode/同 mtime，也要重写成脱敏副本
        return 'update', sst
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


def apply_scrub(src, dst, limit_bytes=256 * 1024 * 1024):
    """copy-on-write 脱敏：先断 hardlink，再写 tmp；源文件不动。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if os.path.getsize(src) > limit_bytes:
            data = None
            reason = 'too-large'
        else:
            data = open(src, 'rb').read()
            reason = ''
    except OSError:
        data = None
        reason = 'unreadable'
    if data is None:
        if os.path.lexists(dst):
            os.unlink(dst)
        shutil.copy2(src, dst)
        return 'copy', 0, False, reason or 'unreadable', ''
    src_sha = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        if os.path.lexists(dst):
            os.unlink(dst)
        shutil.copy2(src, dst)
        return 'copy', 0, False, 'binary', src_sha
    hits = sum(len(rx.findall(text)) for rx, _rep in SECRET_RX)
    clean = scrub_text(text)
    if os.path.lexists(dst):        # 断开 hardlink，绝不改源
        os.unlink(dst)
    tmp = dst + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(clean)
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)
    return 'scrub', hits, True, '', src_sha


def main():
    ap = argparse.ArgumentParser(
        epilog='示例:\n  sp_archive.py\n  sp_archive.py --apply',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true', help='真正写入（默认 dry-run）')
    ap.add_argument('--dry', action='store_true', help='只预览（默认；显式写法）')
    ap.add_argument('--copy', action='store_true', help='强制实体复制，不 hardlink')
    ap.add_argument('--scrub', action='store_true',
                    help='归档时按 S1 同规则脱敏（copy-on-write；源文件不动）')
    ap.add_argument('--rescrub', action='store_true', help='已 scrubbed 的文件也重写一遍')
    ap.add_argument('--only', default='qoder,cc,dsh,pi',
                    help='逗号分隔的源（默认 qoder,cc,dsh,pi；codex 需显式）')
    ap.add_argument('--since', help='只归档最近变更，如 30d / 12h / 2w')
    ap.add_argument('--settle', type=int, default=5, help='跳过 N 秒内还在写的文件（默认 5）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    only = set(x.strip() for x in a.only.split(',') if x.strip())
    since = sp_sources.parse_since(a.since)
    hardlink = not (a.copy or a.scrub)
    prev = load_state()

    stats = {'seen': 0, 'new': 0, 'update': 0, 'skip': 0, 'settling': 0,
             'link': 0, 'copy': 0, 'scrub': 0, 'redactions': 0,
             'unscanned': 0, 'bytes_new': 0, 'roots': 0}
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
                if a.scrub and not a.apply:
                    hits = count_hits(p)
                    records.append({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                                    'src': src, 'action': 'scrub-preview', 'mode': 'dry',
                                    'bytes': st.st_size, 'src_mtime': int(st.st_mtime),
                                    'src_path': p, 'dst_path': dst,
                                    'sensitivity': 'high', 'scrubbed': False,
                                    'redactions': hits if hits is not None else -1})
                    continue
                action, sst = classify(p, dst, hardlink, a.scrub, prev, a.rescrub)
                if action in ('skip', 'missing'):
                    stats['skip'] += 1
                    continue
                stats[action] += 1
                rec = {'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                       'src': src, 'action': action, 'mode': 'dry',
                       'bytes': sst.st_size if sst else 0,
                       'src_mtime': int(sst.st_mtime) if sst else 0,
                       'src_path': p, 'dst_path': dst,
                       'sensitivity': 'high', 'scrubbed': False,
                       'redactions': 0, 'src_sha': '-'}
                if a.apply and a.scrub:
                    mode, hits, scrubbed, note, sha = apply_scrub(p, dst)
                    rec.update({'mode': mode, 'scrubbed': scrubbed, 'redactions': hits,
                                'src_sha': sha, 'note': note})
                    stats[mode] += 1
                    stats['redactions'] += hits
                    if not scrubbed:
                        stats['unscanned'] += 1
                    stats['bytes_new'] += sst.st_size if sst else 0
                elif a.apply:
                    rec['mode'] = apply_one(p, dst, hardlink)
                    stats[rec['mode']] += 1
                    stats['bytes_new'] += sst.st_size if sst else 0
                records.append(rec)

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
            if a.scrub:
                print(f"  scrub {stats['scrub']} · 脱敏 {stats['redactions']} 处 · "
                      f"未扫描/二进制 {stats['unscanned']}")
        else:
            if a.scrub:
                hits = [r for r in records if r.get('redactions', 0) > 0]
                print(f"  scrub 预览：{len(hits)} 个文件命中；--apply 才写（copy-on-write）")
            print('  （未写入；确认后加 --apply）')
    return 0


if __name__ == '__main__':
    sys.exit(main())

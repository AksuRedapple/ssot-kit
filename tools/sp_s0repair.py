#!/usr/bin/env python3
"""sp_s0repair · 修复 2026-11-22 误脱敏留下的「词尾」损伤。

背景：旧 `sp_s0scrub` 用 `sk-[0-9a-f]{5,31}` 与无边界的 `sk-[A-Za-z0-9_-]{20,}`，
把 `task-<hex>` / `ask-at-poorest` / `hard-disk-<hex>` 里的 `sk-...` 当成密钥，
替换成 `[REDACTED-SECRET]`，留下 `ta[REDACTED-SECRET].json` 这类断词。

修复策略（只处理**前一个字符是字母/数字**的标记）：
  1) 用同一会话的未脱敏副本（S1 transcript/raw、索引块、Qoder DB payload、Qoder 日志）
     按左右上下文精确找回原串 → 替换回 `sk-...`；
  2) 找不到 → 退化为 `sk-REDACTED`，至少把词恢复成 `task-REDACTED` / `hard-disk-REDACTED`；
  3) 标点/空白前的标记（真实密钥）不动。
默认 dry-run；`--apply` 才落盘（保 mtime），每次写 `alerts/s0-repair-<ts>.json`。
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
QODER_DB = os.path.expanduser('~/Library/Application Support/com.qoder.app.stable/main.sqlite')
QODER_LOGS = os.path.expanduser('~/.qoder/logs/sessions')
MARK = '[REDACTED-SECRET]'
FALLBACK = 'sk-REDACTED'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sid8_of(path):
    """从 S0 文件名或 S1 目录名取 8 位 sid；取不到返回 ''。"""
    base = os.path.basename(path)
    if '/S1-sessions/' in path or '/S1-subagents/' in path:
        for part in path.split(os.sep):
            m = re.match(r'^\d{4}-\d{2}-\d{2}-([0-9a-f]{8})', part)
            if m:
                return m.group(1)
    m = re.match(r'^([0-9a-f]{8})-[0-9a-f]{4}-', base)
    if m:
        return m.group(1)
    m = re.search(r'([0-9a-f]{8})', base)
    return m.group(1) if m else ''


class Corpus:
    def __init__(self, db=QODER_DB, logs=QODER_LOGS):
        self.db = db
        self.logs = logs
        self._cache = {}

    def for_sid(self, sid8, exclude=None, include_index=False):
        if not sid8:
            return []
        key = (sid8, include_index)
        if key in self._cache:
            return self._cache[key]
        texts = []

        def _add(f):
            if exclude and os.path.abspath(f) == os.path.abspath(exclude):
                return
            if not os.path.isfile(f) or not f.endswith(('.jsonl', '.md')):
                return
            try:
                texts.append(open(f, encoding='utf-8', errors='replace').read())
            except OSError:
                pass

        # 1) 同会话的 S1 派生层（transcript/raw/md，含 S1-subagents）
        for kind in ('S1-sessions', 'S1-subagents'):
            for f in glob.glob(os.path.join(SSOT, 'evidence', '*', kind, f'*{sid8}*', '*')):
                _add(f)
        # 2) Qoder 主库（payload_json 是原始消息）
        try:
            if os.path.exists(self.db):
                con = sqlite3.connect(f'file:{self.db}?mode=ro', uri=True)
                rows = con.execute(
                    "select session_id,payload_json from chat_session_messages "
                    "where session_id like ?", (sid8 + '%',)).fetchall()
                texts.extend(p for _s, p in rows if p)
                con.close()
        except Exception:
            pass
        # 3) S0 原件（可能已修复/回滚；对 S1 派生层是最直接的证据）
        for f in glob.glob(os.path.join(SSOT, 'evidence', '*', 'S0-archive', '**',
                                        f'*{sid8}*.jsonl'), recursive=True):
            if exclude and os.path.abspath(f) == os.path.abspath(exclude):
                continue
            try:
                texts.append(open(f, encoding='utf-8', errors='replace').read())
            except OSError:
                pass
        # 4) Qoder 会话日志
        for f in glob.glob(os.path.join(self.logs, '*', sid8 + '*', 'segments', '*.jsonl')):
            try:
                texts.append(open(f, encoding='utf-8', errors='replace').read())
            except OSError:
                pass
        # 5) 索引块（最后兜底；旧转录可能仍保留未脱敏文本）
        if include_index or not texts:
            try:
                from ssotlib.index import layout
                db = layout.resolve_db()
                if os.path.exists(db):
                    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
                    for (t,) in con.execute("select text from chunks where path like ?",
                                            (f'%{sid8}%',)):
                        if t:
                            texts.append(t)
                    con.close()
            except Exception:
                pass
        self._cache[key] = texts
        return texts


def _token_at(blob, pos, nxt, maxlen=60):
    """pos 指向 sk-；取到右界 nxt 为止的最长 token。"""
    if not blob.startswith('sk-', pos):
        return None
    j = pos + 3
    while j < len(blob) and (blob[j].isalnum() or blob[j] in '_-') and j - pos <= maxlen:
        j += 1
    for k in range(j, pos + 2, -1):
        after = blob[k] if k < len(blob) else ''
        if not nxt or after == nxt:
            return blob[pos:k]
    return None


def _candidates(blob, left, nxt):
    out, start = set(), 0
    while True:
        i = blob.find(left, start)
        if i < 0:
            break
        t = _token_at(blob, i + len(left), nxt)
        if t:
            out.add(t)
        start = i + 1
    return out


def recover(text, corpus, max_ctx=40):
    """→ (new_text, exact, fallback)；只改 alnum 前的标记。"""
    out, pos = [], 0
    exact = fallback = 0
    for m in re.finditer(re.escape(MARK), text):
        if m.start() == 0 or not text[m.start() - 1].isalnum():
            continue
        found = None
        nxt = text[m.end()] if m.end() < len(text) else ''
        for ctx in (max_ctx, 24, 16, 10):
            left = text[max(0, m.start() - ctx):m.start()]
            if not left:
                continue
            cands = set()
            for blob in corpus:
                cands |= _candidates(blob, left, nxt)
            if len(cands) == 1:
                found = cands.pop()
                break
        if not found:
            # 左上下文跨了不同前词时，退到「词前缀」再找一次（task- 的 ta）
            mw = re.search(r'([A-Za-z0-9_-]{1,30})$', text[:m.start()])
            if mw:
                cands = set()
                for blob in corpus:
                    cands |= _candidates(blob, mw.group(1), nxt)
                if len(cands) == 1:
                    found = cands.pop()
        out.append(text[pos:m.start()])
        if found:
            out.append(found)
            exact += 1
        else:
            out.append(FALLBACK)
            fallback += 1
        pos = m.end()
    out.append(text[pos:])
    return ''.join(out), exact, fallback


def redo_fallback(text, corpus, mark=FALLBACK, max_ctx=40):
    """把已退化的 `sk-REDACTED` 再用语料找一次；找不到就保留。"""
    out, pos, exact = [], 0, 0
    for m in re.finditer(re.escape(mark), text):
        if m.start() == 0 or not text[m.start() - 1].isalnum():
            continue
        found = None
        nxt = text[m.end()] if m.end() < len(text) else ''
        for ctx in (max_ctx, 24, 16, 10):
            left = text[max(0, m.start() - ctx):m.start()]
            cands = set()
            for blob in corpus:
                cands |= _candidates(blob, left, nxt)
            if len(cands) == 1:
                found = cands.pop()
                break
        if not found:
            mw = re.search(r'([A-Za-z0-9_-]{1,30})$', text[:m.start()])
            if mw:
                cands = set()
                for blob in corpus:
                    cands |= _candidates(blob, mw.group(1), nxt)
                if len(cands) == 1:
                    found = cands.pop()
        if found:
            out.append(text[pos:m.start()])
            out.append(found)
            pos = m.end()
            exact += 1
    out.append(text[pos:])
    return ''.join(out), exact


def rows_from_manifest(path):
    d = json.load(open(path, encoding='utf-8'))
    return d.get('rows') or []


ROOTS = [
    ('evidence/cc/S0-archive/claude-projects/', '~/.claude/projects/'),
    ('evidence/pi/S0-archive/pi-sessions/', '~/.pi/agent/sessions/'),
    ('evidence/qoder/S0-archive/qoder-projects/', '~/.qoder/projects/'),
    ('evidence/qoder/S0-archive/qoder-memory/', '~/.qoder/memory/'),
    ('evidence/qoder/S0-archive/qoder-aux/', '~/Library/Application Support/Qoder/'),
    ('evidence/dsh/S0-archive/dsh-sessions/', '~/.dsh/sessions/'),
]


def restore_originals(rows, apply=False):
    """从 harness 原始目录恢复与 manifest 前哈希一致的 S0 文件；返回清单。"""
    out = []
    for r in rows:
        if r.get('layer') != 'S0' or not r.get('sha256_before'):
            continue
        rel = r['path']
        for pref, root in ROOTS:
            if not rel.startswith(pref):
                continue
            src = os.path.join(os.path.expanduser(root), rel[len(pref):])
            dst = os.path.join(SSOT, rel)
            if os.path.isfile(src) and sha256(src) == r['sha256_before']:
                out.append({'path': rel, 'source': src})
                if apply:
                    st = os.stat(dst)
                    shutil.copy2(src, dst)
                    os.utime(dst, (st.st_atime, st.st_mtime))
            break
    return out


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_s0repair.py --manifest alerts/s0-scrub-*.json --apply')
    ap.add_argument('--manifest', default=None)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--layers', default='S0,S1-raw,S1')
    ap.add_argument('--sid', default=None)
    ap.add_argument('--restore-originals', action='store_true',
                    help='先从 harness 原始目录恢复哈希一致的 S0（不修词）')
    ap.add_argument('--redo-fallback', action='store_true',
                    help='把 sk-REDACTED 再用修复后的副本找一次（只补精确，不改其他）')
    ap.add_argument('--all-s1', action='store_true',
                    help='扫描全部 S1 transcript/raw（含历史误伤），不只 manifest 行')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    paths = ([a.manifest] if a.manifest else
             sorted(glob.glob(os.path.join(SSOT, 'alerts', 's0-scrub-*.json'))))
    if not paths:
        sys.exit('找不到 s0-scrub 清单')
    if a.all_s1:
        rows = []
        for kind in ('S1-sessions', 'S1-subagents'):
            for f in glob.glob(os.path.join(SSOT, 'evidence', '*', kind, '*', '*')):
                if os.path.isfile(f) and f.endswith(('.jsonl', '.md')):
                    rows.append({'path': os.path.relpath(f, SSOT), 'layer': 'S1'})
    else:
        rows = rows_from_manifest(paths[-1])
    corpus = Corpus()
    if a.redo_fallback:
        n_files = n_exact = 0
        out_rows = []
        layers = {x.strip() for x in a.layers.split(',')}
        scan = []
        for f in glob.glob(os.path.join(SSOT, 'evidence', '**', '*'), recursive=True):
            if not os.path.isfile(f) or not f.endswith(('.jsonl', '.json', '.md', '.txt')):
                continue
            rel = os.path.relpath(f, SSOT)
            layer = 'S0' if 'S0-archive' in rel else (
                'S1-raw' if rel.endswith('raw.jsonl') else 'S1')
            if layer not in layers:
                continue
            try:
                if FALLBACK in open(f, encoding='utf-8', errors='replace').read():
                    scan.append({'path': rel, 'layer': layer})
            except OSError:
                pass
        rows = scan
        for r in rows:
            if r.get('layer') not in {x.strip() for x in a.layers.split(',')}:
                continue
            p = os.path.join(SSOT, r['path'])
            if not os.path.isfile(p):
                continue
            text = open(p, encoding='utf-8', errors='replace').read()
            if FALLBACK not in text:
                continue
            new, exact = redo_fallback(text, corpus.for_sid(sid8_of(p), exclude=p, include_index=True))
            if exact:
                n_files += 1
                n_exact += exact
                out_rows.append({'path': r['path'], 'exact': exact})
                if not a.quiet:
                    print(f'  {exact:3d} 精确  {r["path"]}')
                if a.apply:
                    st = os.stat(p)
                    tmp = p + '.repair.tmp'
                    with open(tmp, 'w', encoding='utf-8') as f:
                        f.write(new)
                    os.replace(tmp, p)
                    os.utime(p, (st.st_atime, st.st_mtime))
        print(f'{"APPLY" if a.apply else "DRY-RUN"} redo-fallback：{n_files} 文件 / 精确 {n_exact}')
        if a.apply:
            os.makedirs(os.path.join(SSOT, 'alerts'), exist_ok=True)
            out = os.path.join(SSOT, 'alerts', 's0-repair-fallback-%s.json' %
                               datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            json.dump({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                       'files': n_files, 'exact': n_exact, 'rows': out_rows},
                      open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print(f'清单 → {os.path.relpath(out, SSOT)}')
        return 0
    if a.restore_originals:
        restored = restore_originals(rows, apply=a.apply)
        print(f'{"APPLY" if a.apply else "DRY-RUN"} restore-originals：{len(restored)} 个文件'
              + ('' if a.apply else '（未写入）'))
        for x in restored[:10]:
            print(f'  {x["path"]} ← {x["source"]}')
        if not a.apply:
            return 0
        os.makedirs(os.path.join(SSOT, 'alerts'), exist_ok=True)
        out = os.path.join(SSOT, 'alerts',
                           's0-restore-%s.json' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        json.dump({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                   'files': len(restored), 'rows': restored},
                  open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'清单 → {os.path.relpath(out, SSOT)}')
        return 0
    layers = {x.strip() for x in a.layers.split(',')}
    out_rows = []
    n_files = n_exact = n_fb = 0
    for r in rows:
        if r.get('layer') not in layers:
            continue
        p = os.path.join(SSOT, r['path'])
        if not os.path.isfile(p):
            continue
        if a.sid and a.sid not in r['path']:
            continue
        try:
            text = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        if MARK not in text:
            continue
        sid8 = sid8_of(p)
        new, exact, fb = recover(text, corpus.for_sid(sid8, exclude=p))
        if exact or fb:
            n_files += 1
            n_exact += exact
            n_fb += fb
            row = {'path': r['path'], 'layer': r['layer'], 'exact': exact,
                   'fallback': fb, 'sha256_before': sha256(p)}
            out_rows.append(row)
            if not a.quiet:
                print(f'  {exact:3d} 精确 / {fb:3d} 退化  {r["path"]}')
            if a.apply:
                st = os.stat(p)
                tmp = p + '.repair.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(new)
                os.replace(tmp, p)
                os.utime(p, (st.st_atime, st.st_mtime))
                row['sha256_after'] = sha256(p)
    print(f'{"APPLY" if a.apply else "DRY-RUN"}：{n_files} 文件 / 精确 {n_exact} / 退化 {n_fb}')
    if not a.apply:
        print('  （未写入；确认后加 --apply）')
        return 0
    os.makedirs(os.path.join(SSOT, 'alerts'), exist_ok=True)
    out = os.path.join(SSOT, 'alerts',
                       's0-repair-%s.json' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    json.dump({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
               'manifest': paths[-1], 'files': n_files, 'exact': n_exact,
               'fallback': n_fb, 'rows': out_rows},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'清单 → {os.path.relpath(out, SSOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

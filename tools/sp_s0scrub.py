#!/usr/bin/env python3
"""sp_s0scrub · 证据层就地脱敏（把密钥形态换成 [REDACTED-SECRET]，不删原件）

背景：`sp_s0scan` 只能证明「有命中」，不能消除命中。S1 与索引都有脱敏/隐私闸，
但 S0 原文是它们的上游——上游不干净，派生层干净只是「这次导出干净」。

纪律：
  · 范围默认是**整个 evidence/**：S0 原文、S1 `raw.jsonl` 副本、S1 transcript 都算
    （只清 S0 会留下 855 处 raw 副本 + 少量 transcript 命中——2026-11-22 实测）
  · 只替换 `ssotlib.ingest.SECRET_RX` 命中的片段；其余字节不动
  · 保留 mtime（否则 sp_convert/sp_dsh 的增量会把 103 个会话全判变、重转一轮）
  · write 前校验 JSONL 每行仍可解析（替换文本不含引号/反斜杠，理论上不会破坏，
    但上游格式不保证，宁可整文件跳过并报错）
  · 每次运行写清单 `alerts/s0-scrub-<ts>.json`（只有路径/计数/前后 sha256，无内容）
  · 默认 dry-run；`--apply` 才落盘且不可逆（policy: scrub is opt-in and irreversible）

用法:
  python3 tools/sp_s0scrub.py                 # dry-run：列文件与计数
  python3 tools/sp_s0scrub.py --apply         # 就地脱敏
  python3 tools/sp_s0scrub.py --only qoder    # 只处理某个 harness
  python3 tools/sp_s0scrub.py --scope s0      # 只处理 S0-archive（旧行为）
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib.ingest import SECRET_RX  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
EXTS = ('.jsonl', '.json', '.md', '.txt')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
MAX_BYTES = 256 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def scrub_text(text):
    """→ (new_text, counts_by_pattern, total)"""
    counts = [0] * len(SECRET_RX)
    for i, (rx, rep) in enumerate(SECRET_RX):
        text, n = rx.subn(rep, text)
        counts[i] = n
    return text, counts, sum(counts)


def valid_jsonl(text):
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            json.loads(ln)
        except Exception:
            return False
    return True


def files(only=None, scope='evidence'):
    root = os.path.join(SSOT, 'evidence')
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        parts = dp.split(os.sep)
        if scope == 's0' and 'S0-archive' not in parts:
            continue
        if only:
            try:
                i = parts.index('evidence')
            except ValueError:
                i = -1
            h = parts[i + 1] if 0 <= i < len(parts) - 1 else ''
            if h not in only:
                continue
        for fn in sorted(fns):
            if fn.endswith(EXTS):
                yield os.path.join(dp, fn)


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_s0scrub.py --apply\n  sp_s0scrub.py --only qoder --apply')
    ap.add_argument('--apply', action='store_true', help='真正落盘（默认 dry-run）')
    ap.add_argument('--only', help='逗号分隔的 harness（如 pi,cc）；只处理这些源')
    ap.add_argument('--scope', choices=['evidence', 's0'], default='evidence',
                    help='evidence=全证据层（默认）；s0=只清 S0-archive')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(',')} if a.only else None

    rows, n_files, n_hits, n_skip = [], 0, 0, 0
    for p in files(only, a.scope):
        try:
            if os.path.getsize(p) > MAX_BYTES:
                n_skip += 1
                continue
            raw = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            n_skip += 1
            continue
        new, counts, total = scrub_text(raw)
        if not total:
            continue
        if p.endswith('.jsonl') and not valid_jsonl(new):
            print(f'❌ 跳过（脱敏后 JSONL 不可解析）：{os.path.relpath(p, SSOT)}', file=sys.stderr)
            n_skip += 1
            continue
        n_files += 1
        n_hits += total
        rel = os.path.relpath(p, SSOT)
        layer = 'S0' if 'S0-archive' in rel else ('S1-raw' if rel.endswith('raw.jsonl') else 'S1')
        row = {'path': rel, 'layer': layer, 'matches': total,
               'by_pattern': counts, 'sha256_before': sha256(p)}
        rows.append(row)
        if not a.quiet:
            print(f'  {total:4d}  {os.path.relpath(p, SSOT)}')
        if a.apply:
            st = os.stat(p)
            tmp = p + '.scrub.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(new)
            os.replace(tmp, p)
            os.utime(p, (st.st_atime, st.st_mtime))     # 增量判变靠 mtime，必须保
            row['sha256_after'] = sha256(p)

    print(f'{"APPLY" if a.apply else "DRY-RUN"}（{a.scope}）：{n_files} 文件 / {n_hits} 处'
          + (f' / 跳过 {n_skip}' if n_skip else ''))
    if not a.apply:
        print('  （未写入；确认后加 --apply，不可逆）')
        return 0 if not n_hits else 0
    os.makedirs(os.path.join(SSOT, 'alerts'), exist_ok=True)
    out = os.path.join(SSOT, 'alerts',
                       's0-scrub-%s.json' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    json.dump({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
               'files': n_files, 'matches': n_hits, 'skipped': n_skip, 'rows': rows},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'清单 → {os.path.relpath(out, SSOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

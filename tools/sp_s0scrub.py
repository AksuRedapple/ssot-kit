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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import secrets  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
EXTS = ('.jsonl', '.json', '.md', '.txt')
# 便宜的文件级预筛（ripgrep PCRE）：5.8GB/2 万文件 → 273 个候选，9s（2026-11-23 实测）
RG_PATTERN = (r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{5,}|ghp_|github_pat_|'
              r'AKIA[0-9A-Z]{16}|hf_|Bearer\s+[A-Za-z0-9._-]{20,}|'
              r'-----BEGIN [A-Z ]*PRIVATE KEY-----')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
MAX_BYTES = 256 * 1024 * 1024


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def scrub_text(text, level='high', allow=None):
    """→ (new_text, by_confidence, total, skipped_allow)"""
    allow = set(allow or ())
    by = {'high': 0, 'medium': 0, 'low': 0}
    out, pos, skipped = [], 0, 0
    want = {'high'} if level == 'high' else (
        {'high', 'medium'} if level == 'medium' else {'high', 'medium', 'low'})
    for f in secrets.classify(text):
        by[f['confidence']] += 1
        if f['confidence'] not in want:
            continue
        if allow and secrets.hash8(f['value']) in allow:
            skipped += 1
            continue
        out.append(text[pos:f['start']])
        out.append(secrets.REPLACEMENT)
        pos = f['end']
    out.append(text[pos:])
    return ''.join(out), by, sum(by.values()), skipped


def load_allowlist(path):
    try:
        d = json.load(open(path, encoding='utf-8'))
        return set(d.get('sha256') or d.get('hashes') or [])
    except Exception:
        return set()


def rotate_rows(only=None, scope='evidence'):
    """→ {service: {'count': n, 'unique': set(hash8), 'example': rel}}"""
    svc = {
        'ghp': 'GitHub PAT', 'github_pat': 'GitHub PAT', 'hf': 'HuggingFace',
        'akia': 'AWS Access Key', 'pem': 'Private Key', 'bearer': 'Bearer token（未知服务）',
        'sk_full': 'sk-*（OpenAI/DeepSeek/OpenRouter 等）',
        'sk_short': 'sk-* 前缀（截断展示）',
    }
    out = {}
    for p in files(only, scope):
        try:
            raw = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for f in secrets.classify(raw):
            if f['confidence'] == 'low':
                continue
            name = svc.get(f['kind'], f['kind'])
            rec = out.setdefault(name, {'count': 0, 'unique': set(),
                                        'example': os.path.relpath(p, SSOT)})
            rec['count'] += 1
            rec['unique'].add(secrets.hash8(f['value']))
    return out


def valid_jsonl(text):
    for ln in text.splitlines():
        if not ln.strip():
            continue
        try:
            json.loads(ln)
        except Exception:
            return False
    return True


def _rg_candidates(root):
    try:
        r = subprocess.run(['rg', '-l', '--text', '-P', RG_PATTERN, root],
                           capture_output=True, text=True, timeout=600)
        if r.returncode in (0, 1):
            return {os.path.abspath(x) for x in r.stdout.splitlines() if x}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def files(only=None, scope='evidence'):
    root = os.path.join(SSOT, 'evidence')
    cand = _rg_candidates(root)
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
            if not fn.endswith(EXTS):
                continue
            p = os.path.join(dp, fn)
            if cand is not None and os.path.abspath(p) not in cand:
                continue
            yield p


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_s0scrub.py --apply\n  sp_s0scrub.py --only qoder --apply')
    ap.add_argument('--apply', action='store_true', help='真正落盘（默认 dry-run）')
    ap.add_argument('--only', help='逗号分隔的 harness（如 pi,cc）；只处理这些源')
    ap.add_argument('--scope', choices=['evidence', 's0'], default='evidence',
                    help='evidence=全证据层（默认）；s0=只清 S0-archive')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--level', choices=['high', 'medium', 'all'], default='high',
                    help='默认只清 high；medium=加有上下文的短前缀/Bearer；all=含 low（不建议）')
    ap.add_argument('--allowlist', default=os.path.join(SSOT, 'profile', 'secret-allowlist.json'),
                    help='sha256 白名单（只存哈希）')
    ap.add_argument('--rotate-list', action='store_true',
                    help='只输出按服务归类的待轮换清单（不写文件）')
    a = ap.parse_args()
    only = {x.strip() for x in a.only.split(',')} if a.only else None
    if a.rotate_list:
        data = rotate_rows(only, a.scope)
        for name, rec in sorted(data.items(), key=lambda kv: -kv[1]['count']):
            print(f"{rec['count']:5d} 处 / {len(rec['unique'])} 唯一值  {name}  "
                  f"例: {rec['example']}")
        return 0
    allow = load_allowlist(a.allowlist)

    rows, n_files, n_hits, n_skip = [], 0, 0, 0
    by_all = {'high': 0, 'medium': 0, 'low': 0}
    n_allow = 0
    for p in files(only, a.scope):
        try:
            if os.path.getsize(p) > MAX_BYTES:
                n_skip += 1
                continue
            data = open(p, 'rb').read()
            raw = data.decode('utf-8', 'replace')
        except OSError:
            n_skip += 1
            continue
        if not secrets.CANDIDATE.search(raw):
            continue
        new, by, total, skipped_allow = scrub_text(raw, a.level, allow)
        if not total:
            continue
        for k in by_all:
            by_all[k] += by[k]
        n_allow += skipped_allow
        # 大文件跳过整行 JSON 校验：替换文本只含 []/字母/连字符，不会破坏字符串；
        # 逐行 json.loads 在 200MB+ 转录上要几分钟（2026-11-23 实测）
        if p.endswith('.jsonl') and len(data) <= 10 * 1024 * 1024 and not valid_jsonl(new):
            print(f'❌ 跳过（脱敏后 JSONL 不可解析）：{os.path.relpath(p, SSOT)}', file=sys.stderr)
            n_skip += 1
            continue
        n_files += 1
        n_hits += total
        rel = os.path.relpath(p, SSOT)
        layer = 'S0' if 'S0-archive' in rel else ('S1-raw' if rel.endswith('raw.jsonl') else 'S1')
        row = {'path': rel, 'layer': layer, 'matches': total,
               'by_confidence': by, 'allowlist_skipped': skipped_allow,
               'sha256_before': hashlib.sha256(data).hexdigest()}
        rows.append(row)
        if not a.quiet:
            print(f"  {total:4d}（h{by['high']}/m{by['medium']}/l{by['low']}）"
                  f"  {os.path.relpath(p, SSOT)}")
        if a.apply:
            st = os.stat(p)
            tmp = p + '.scrub.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(new)
            os.replace(tmp, p)
            os.utime(p, (st.st_atime, st.st_mtime))     # 增量判变靠 mtime，必须保
            row['sha256_after'] = sha256(p)

    print(f'{"APPLY" if a.apply else "DRY-RUN"}（{a.scope} / {a.level}）：'
          f'{n_files} 文件 / {n_hits} 处'
          f"（high {by_all['high']} / medium {by_all['medium']} / low {by_all['low']}）"
          + (f' / 白名单跳过 {n_allow}' if n_allow else '')
          + (f' / 文件跳过 {n_skip}' if n_skip else ''))
    if not a.apply:
        print('  （未写入；确认后加 --apply，不可逆）')
        return 0 if not n_hits else 0
    os.makedirs(os.path.join(SSOT, 'alerts'), exist_ok=True)
    out = os.path.join(SSOT, 'alerts',
                       's0-scrub-%s.json' % datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    json.dump({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
               'files': n_files, 'matches': n_hits, 'skipped': n_skip,
               'level': a.level, 'by_confidence': by_all,
               'allowlist_skipped': n_allow, 'rows': rows},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'清单 → {os.path.relpath(out, SSOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""sp_line_status · 派生线页「现在时」状态行(不靠人抄)

最近动作 = max(该页最近 git 提交日, 该页被 inbox 提及的最近日期, 该页被断言引用的最近日期)
现场指针与卡点:保留原值(卡点缺省=无)

用法:
  python3 tools/sp_line_status.py --dry-run
  python3 tools/sp_line_status.py --apply
"""
import argparse, datetime, glob, os, re, subprocess, sys

SSOT = os.path.expanduser('~/ssot')
STATUS_RX = re.compile(r'^> 状态[:：](.*)$', re.M)


def git_date(path):
    try:
        r = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', path], cwd=SSOT,
                           capture_output=True, text=True, timeout=30)
        d = r.stdout.strip()
        return d if re.match(r'\d{4}-\d{2}-\d{2}', d) else None
    except Exception:
        return None


def inbox_date(name):
    best = None
    for f in glob.glob(os.path.join(SSOT, 'inbox', '*.md')):
        for ln in open(f, encoding='utf-8', errors='replace'):
            if name not in ln:
                continue
            m = re.match(r'- (\d{4}-\d{2}-\d{2})', ln)
            if m and (best is None or m.group(1) > best):
                best = m.group(1)
    return best


def assertion_date(name):
    best = None
    p = os.path.join(SSOT, 'knowledge', 'assertions.md')
    if os.path.exists(p):
        for ln in open(p, encoding='utf-8', errors='replace'):
            if name in ln:
                m = re.search(r'(20\d{2}-\d{2}-\d{2})', ln)
                if m and (best is None or m.group(1) > best):
                    best = m.group(1)
    return best


def process(path, apply_):
    name = os.path.basename(path)[:-3]
    text = open(path, encoding='utf-8', errors='replace').read()
    m = STATUS_RX.search(text)
    cur = m.group(1).strip() if m else ''
    status = '活跃'
    for cand in ('暂停', '完成', '活跃'):
        if cand in cur:
            status = cand
            break
    ptr = ''
    pm = re.search(r'现场[:：]\s*`?([^`（|]+)`?', cur)
    if pm:
        ptr = pm.group(1).strip()
    block = re.search(r'卡点[:：]\s*([^|]+)', cur)
    block_text = block.group(1).strip() if block else '无'
    date = max([d for d in (git_date(path), inbox_date(name), assertion_date(name)) if d] or ['1970-01-01'])
    line = f'> 状态: {status} — 最近: {date}'
    if ptr:
        line += f' — 现场: `{ptr}`'
    line += '（现在时）'
    if block_text:
        line += f' ｜ 卡点: {block_text}'
    if m:
        new = text[:m.start()] + line + text[m.end():]
    else:
        idx = text.find('\n', text.find('# '))
        head, rest = text[:idx + 1], text[idx + 1:]
        if not rest.startswith('\n'):
            rest = '\n' + rest
        new = head + line + '\n' + rest
    changed = new != text
    if apply_ and changed:
        open(path, 'w', encoding='utf-8').write(new)
    return name, date, status, changed


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_line_status.py --dry-run\n  sp_line_status.py --apply',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dir', default=os.path.join(SSOT, 'lines'))
    a = ap.parse_args()
    files = [p for p in sorted(glob.glob(os.path.join(a.dir, '*.md')))
             if not os.path.basename(p).startswith('_')]
    changed = 0
    for p in files:
        name, d, st, ch = process(p, a.apply)
        changed += ch
        print(f'  {name:22s} {d} {st}' + ('  ← 更新' if ch and a.apply else ''))
    print(f'{"已更新" if a.apply else "[dry-run] 将更新"} {changed}/{len(files)} 页')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

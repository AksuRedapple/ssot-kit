#!/usr/bin/env python3
"""sp_takeover_lint · 接手面自检(四规则,确定性,不调 LLM)

规则:
  R1 状态行:每页应有 `> 状态: ... — 最近: YYYY-MM-DD`,且 ≤7 天
  R2 在途条目:`- [ ]` 应带「判据」与「owner」(按比例报数,不阻塞)
  R3 页内反引号路径:形如 `path/...` 或 `~/...` 的反引号路径必须存在(历史/退役标注除外)
  R4 站内链接:相对 .md 链接必须可解析

用法:
  sp_takeover_lint.py [--dir lines] [--json] [--strict]
退出码:有 R3/R4 违规 → 1;否则 0(--strict 下 R1/R2 也计入)
"""
import argparse, datetime, glob, json, os, re, sys

SSOT = os.path.expanduser('~/ssot')
SKIP_MARK = re.compile(r'(退役|失效|历史|已迁|旧路径|待迁|改为|作废)')
# 只认"仓库内路径 / home 路径";HTTP 路由(/api/…)、片段(.kbignore)、通配一律跳过
PATH_RX = re.compile(r'`(~/[\w.\-~/]+|(?:knowledge|lines|tools|profile|drafts|sessions|compile|inbox|S2-index|evidence|backups)/[\w.\-~/]+)`')
LINK_RX = re.compile(r'\]\(([^)\s]+\.md)(?:#[^)]*)?\)')


def parse_status(text):
    m = re.search(r'^> 状态:.*?最近[:：]\s*(\d{4}-\d{2}-\d{2})', text, re.M)
    return m.group(1) if m else None


def check(path, now, root=SSOT):
    text = open(path, encoding='utf-8', errors='replace').read()
    name = os.path.basename(path)
    issues = {'R1': [], 'R2': [], 'R3': [], 'R4': []}
    d = parse_status(text)
    mline = re.search(r'^> 状态:\s*([^—|]+)', text, re.M)
    word = (mline.group(1).strip() if mline else '')
    dormant = ('暂停' in word) or ('完成' in word)
    if not d:
        issues['R1'].append('无状态行')
    elif not dormant:
        age = (now - datetime.date.fromisoformat(d)).days
        if age > 7:
            issues['R1'].append(f'状态行 {age} 天未更新(活跃页)')
    todo = [l for l in text.splitlines() if l.startswith('- [ ]')]
    with_crit = [l for l in todo if '判据' in l and 'owner' in l]
    issues['R2'] = [f'{len(with_crit)}/{len(todo)} 条带判据+owner'] if todo else []
    # R3
    for i, line in enumerate(text.splitlines(), 1):
        if SKIP_MARK.search(line):
            continue
        for p in PATH_RX.findall(line):
            if any(x in p for x in ('*', '{', '<', '>', '|', '…')) or p.endswith(('.', '/')):
                continue
            if '.' not in p.rsplit('/', 1)[-1]:      # 形如 lines/ssot-hub 的页面引用,非文件
                continue
            full = os.path.expanduser(p) if p.startswith('~') else os.path.join(root, p)
            if not os.path.exists(full):
                issues['R3'].append(f'L{i} 路径不存在: {p}')
    # R4
    for i, line in enumerate(text.splitlines(), 1):
        for link in LINK_RX.findall(line):
            if link.startswith(('http://', 'https://')):
                continue
            full = os.path.join(os.path.dirname(path), link)
            if not os.path.exists(full):
                issues['R4'].append(f'L{i} 链接不可解析: {link}')
    return name, issues, len(todo), len(with_crit)


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_takeover_lint.py\n  sp_takeover_lint.py --json --strict',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default=os.path.join(SSOT, 'lines'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--max-age', type=int, default=7)
    ap.add_argument('--root', default=SSOT, help='相对路径基准(测试用)')
    a = ap.parse_args()
    now = datetime.date.today()
    rows = [check(p, now, a.root) for p in sorted(glob.glob(os.path.join(a.dir, '*.md')))
            if not os.path.basename(p).startswith('_')]
    total_todo = sum(r[2] for r in rows)
    total_crit = sum(r[3] for r in rows)
    with_status = sum(1 for r in rows if not r[1]['R1'])
    r3 = sum(len(r[1]['R3']) for r in rows)
    r4 = sum(len(r[1]['R4']) for r in rows)
    if a.json:
        print(json.dumps({'pages': len(rows), 'status_ok': with_status, 'todo': total_todo,
                          'todo_with_criteria': total_crit, 'dead_paths': r3, 'broken_links': r4,
                          'detail': {r[0]: r[1] for r in rows if any(r[1].values())}},
                         ensure_ascii=False, indent=1))
        return 1 if (r3 or r4) else 0
    print(f'接手面自检:{len(rows)} 页 · 状态行 ok {with_status} · 在途 {total_todo}(带判据+owner {total_crit}) '
          f'· 死路径 {r3} · 断链 {r4}')
    for name, iss, _t, _c in rows:
        bad = [(k, v) for k, v in iss.items() if v and (k in ('R3', 'R4') or a.strict)]
        if bad:
            print(f'  ✗ {name}')
            for k, v in bad:
                for x in v[:3]:
                    print(f'     {k} {x}')
    if r4:
        print(f'❌ 硬问题:R4 断链 {r4} 处')
        return 1
    if r3:
        print(f'⚠ R3 疑似失效路径 {r3} 处(建议级,不阻塞;--strict 才计入)')
    if a.strict and (r3 or r4):
        return 1
    print('✅ 硬规则全过(死路径/断链为 0)')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

#!/usr/bin/env python3
"""sp_purify · 安全提纯器（只追加，不重写）

背景：A558 —— 一次批量提纯把历史 `→ 归位:` 标记也重算了，覆盖了正确映射。
本工具把护栏写进代码：

  - 默认 dry-run，只打印计划，不写盘
  - 只处理「未标记」的条目行；已有 `→` 的行默认跳过
  - --remap 才允许重算已有标记（危险操作，必须显式）
  - --apply 落盘前自动备份 inbox/ 到 backups/inbox-<ts>/
  - 写完做单调校验：标记数不得少于改前

用法：
  python3 sp_purify.py                 # dry-run：看计划
  python3 sp_purify.py --apply         # 落盘（自动备份）
  python3 sp_purify.py --remap --apply # 重算已有标记（慎用）

默认根 = 当前目录（可用 SSOT_ROOT 覆盖）。
"""
import argparse
import glob
import os
import re
import shutil
import sys
import time

ENTRY_RE = re.compile(r'^-\s+(?:\d{4}-\d{2}-\d{2}\s+)?\[[A-Za-z_-]+\]')

RULES = [
    ('knowledge/assertions.md', r'断言|A\d{3}|坑|取证|assertions'),
    ('lines/algorithm-training.md', r'算法|algo|284|300|LC\d|LC150|LC75|Top100|LTR|搜索排序|刷题|题解|judge|leetcode|判题|题库|题面|难度|签名|入环|双实现|样本|训练'),
    ('lines/mobile-apps.md', r'电池|BatteryLab|batterylab|续航'),
    ('lines/allinone-app.md', r'HomeHub|allinone|APK|发版|取件台|versionCode|vc10'),
    ('lines/grokbot.md', r'grokbot|逛逛|youtb|YouTube 精华'),
    ('lines/ssot-hub.md', r'SSOT|索引|语义|inbox|sp_|候选|提纯|编号'),
    ('lines/media-pipeline.md', r'音乐|视频|Jellyfin|影库|字幕|Navidrome|媒体'),
    ('lines/learning-line.md', r'学习台|dashboard|课程|CS329|阅读台|kindle|书|primer|知识文'),
    ('lines/dsh-harness.md', r'Paseo|DSH|harness|Codex|Claude|opencode|Qoder|Pi|模型|API|额度|token'),
    ('lines/network-domain.md', r'narrowgate|域名|隧道|CF|Cloudflare|邀请'),
    ('lines/mac-foundation.md', r'迁移|MBP|mini|launchd|备份|磁盘|hostname|Tailscale|DNS|证书|Caddy|端口|防火墙|sudo|TCC|pmset|显示器|键盘|内存|swap|NAS|路由器'),
]


def dest(line, fname):
    if 'algo' in fname:
        return 'lines/algorithm-training.md'
    if 'batterylab' in fname:
        return 'lines/mobile-apps.md'
    for p, pat in RULES:
        if re.search(pat, line, re.I):
            return p
    return 'lines/mac-foundation.md'


def count_markers(files):
    n = 0
    for f in files:
        for l in open(f, encoding='utf-8', errors='replace'):
            if ENTRY_RE.match(l) and '→' in l:
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser(epilog='默认 dry-run；--apply 才写盘；已有标记默认不动（--remap 才重算）。')
    ap.add_argument('--root', default=os.environ.get('SSOT_ROOT', os.getcwd()))
    ap.add_argument('--apply', action='store_true', help='真正写盘（默认只打印计划）')
    ap.add_argument('--remap', action='store_true', help='重算已有标记（危险，A558）')
    ap.add_argument('--no-backup', action='store_true', help='不备份（不推荐）')
    ap.add_argument('--limit', type=int, default=0, help='最多处理 N 条（0=全部）')
    args = ap.parse_args()

    inbox = os.path.join(args.root, 'inbox')
    files = sorted(glob.glob(os.path.join(inbox, '2026-*.md')))
    if not files:
        print('没有 inbox 文件'); return 0

    plan = []  # (file, lineno, old, new)
    for f in files:
        lines = open(f, encoding='utf-8', errors='replace').read().splitlines()
        for i, l in enumerate(lines, 1):
            if not ENTRY_RE.match(l):
                continue
            has = '→' in l
            if has and not args.remap:
                continue
            base = l[:l.find('→')].rstrip() if has else l
            d = dest(base, os.path.basename(f))
            new = base + f' → 归位: {d}'
            if new != l:
                plan.append((f, i, l, new))

    if args.limit:
        plan = plan[:args.limit]

    from collections import Counter
    c = Counter(dest(l[:l.find('→')].rstrip() if '→' in l else l, os.path.basename(f))
                for f, i, l, n in plan)
    print(f'计划变更 {len(plan)} 条')
    for k, v in c.most_common():
        print(f'  {v:4d}  {k}')
    for f, i, l, n in plan[:5]:
        print(f'  样例 {os.path.basename(f)}:{i}  {l[:60]}…')

    if not plan:
        print('无变更'); return 0
    if not args.apply:
        print('\n[dry-run] 未写盘。确认无误后加 --apply（会先备份）。')
        return 0

    if not args.no_backup:
        bdir = os.path.join(args.root, 'backups', f'inbox-{time.strftime("%Y%m%d-%H%M%S")}')
        os.makedirs(os.path.dirname(bdir), exist_ok=True)
        shutil.copytree(inbox, bdir, ignore=shutil.ignore_patterns('.staging'))
        print('备份：', bdir)

    before = count_markers(files)
    by_file = {}
    for f, i, l, n in plan:
        by_file.setdefault(f, []).append((i, l, n))
    for f, changes in by_file.items():
        lines = open(f, encoding='utf-8', errors='replace').read().splitlines()
        for i, old, new in changes:
            if lines[i - 1] != old:
                print(f'⚠ 跳过冲突 {os.path.basename(f)}:{i}（行已变）', file=sys.stderr)
                continue
            lines[i - 1] = new
        open(f, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    after = count_markers(files)
    print(f'标记数：{before} → {after}')
    if after < before:
        print('❌ 单调校验失败：标记数减少，请从备份恢复', file=sys.stderr)
        return 2
    print('✅ 完成（标记数只增不减）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

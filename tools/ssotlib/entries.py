"""条目与标记：inbox 条目判定的唯一实现（A558 单一真相）。

A558 事故：提纯把历史 `→ 归位:` 标记重算、覆盖了正确映射。根因之一是
「什么算一条条目」在 ssot_check 与 sp_purify 各有一份，改一处漏一处。
此后 ENTRY_RE / is_entry / 标记计数 / conf 解析只允许从这里引用。
"""
import glob
import os
import re
import subprocess

# 「- [type] ...」或「- YYYY-MM-DD [type] ...」
ENTRY_RE = re.compile(r'^-\s+(?:\d{4}-\d{2}-\d{2}\s+)?\[[A-Za-z_-]+\]')
MARK = '→'
CONF_PREFIXES = ('实测', '推断', '推算', '待核')
# (?<![\w.]) 防误命中文件名/配置键：`_meta/agents.conf:pi 行` 曾被当成 conf 值；
# 值到 `|`/`｜`/全角括号/反引号/换行即止，防正文里提到 `conf:` 时把后文整段吃成值
CONF_RE = re.compile(r'(?<![\w.])conf:\s*([^|｜（`\n]+)')
# 决定 / 决策 / 用户令 / owner 是“谁定的”，不是置信度，不参与 conf
CONF_NON_VALUES = ('决定', '决策', '用户令', 'owner')


def is_entry(line):
    """inbox 里只有「- [type] ...」或「- YYYY-MM-DD [type] ...」才算一条贡献；
    结构化笔记（如 lanshare 的要点列表）不是条目，不计入未提纯。"""
    return bool(ENTRY_RE.match(line))


def has_marker(line):
    """条目行是否已带 `→` 归位标记（非条目行里的箭头不算）。"""
    return is_entry(line) and MARK in line


def _lines(path):
    """逐行读出；坏字节用 replacement，不让一行乱码中断整份体检。"""
    with open(path, encoding='utf-8', errors='replace') as f:
        yield from f


def inbox_files(root):
    """inbox 下的正本条目文件；README 是说明页，不算。"""
    return [p for p in sorted(glob.glob(os.path.join(root, 'inbox', '*.md')))
            if os.path.basename(p) != 'README.md']


def marker_count_files(paths):
    """给定文件列表里的标记条目数（sp_purify 对「本次计划涉及的文件」计数时用）。"""
    n = 0
    for p in paths:
        for line in _lines(p):
            if has_marker(line):
                n += 1
    return n


def marker_count(root):
    """当前工作区里带 `→` 标记的条目数（只认条目行）。"""
    return marker_count_files(inbox_files(root))


def pending_count(root):
    """未提纯条目数：是条目且没有 `→`。"""
    n = 0
    for p in inbox_files(root):
        for line in _lines(p):
            if is_entry(line) and MARK not in line:
                n += 1
    return n


def head_marker_count(root):
    """HEAD 里的标记条目数；git 不可用/无 HEAD 时返回 None。"""
    try:
        out = subprocess.run(['git', '-C', root, 'grep', '-h', MARK, 'HEAD', '--', 'inbox'],
                             capture_output=True, text=True)
        if out.returncode not in (0, 1):
            return None
        return sum(1 for line in out.stdout.splitlines() if has_marker(line))
    except Exception:
        return None


def normalize_conf(value):
    """把常见 conf 写法归一到四前缀；决定/用户令这类无置信度的行返回 None。

    归一规则（2026-11-14 放宽，只认语义不认字面）：
    - 实测：亲自跑过/亲眼看过 —— 实测、设备实测、代码、单测、源码、编译、现场、
      对端实测（对方实测回执）、明示（来源明确陈述，非推断）、以及「0 ERROR / PASS / 全绿」这类检查结果
    - 推断：文档核验 / 文档（照文档写的，没装机跑）
    - 推算 / 待核：原样
    """
    v = (value or '').strip().strip('*').strip()
    if not v:
        return None
    hits = []
    for part in re.split(r'[+/，,、;；]', v):
        p = part.strip().strip('*').strip()
        if not p:
            continue
        if p.startswith(('实测', '设备实测', '代码', '单测', '编译', '现场', '对端实测', '源码', '明示')):
            hits.append('实测')
        elif re.search(r'0\s*ERROR|\bPASS\b|全绿|全过', p):
            # conf 里写的是“检查结果”而不是置信度短语：按实测计入，别当非法值刷屏
            hits.append('实测')
        elif p.startswith('推算'):
            hits.append('推算')
        elif p.startswith(('推断', '文档')):
            hits.append('推断')
        elif p.startswith('待核'):
            hits.append('待核')
    for x in ('实测', '推算', '推断', '待核'):
        if x in hits:
            return x
    return None


def parse_conf(line):
    """抽一行里的 conf 值；去掉行尾 `→ 归位` 标记；非置信度语义返回 None。"""
    m = CONF_RE.search(line)
    if not m:
        return None
    value = re.split(MARK, m.group(1))[0].strip()
    if value.startswith(CONF_NON_VALUES):
        return None
    return value


def inbox_stats(root):
    """→ {total, conf, bad, normalized}；bad 为无法归一的原始值列表。"""
    total = conf = normalized = 0
    bad = []
    for p in inbox_files(root):
        for line in _lines(p):
            if not is_entry(line):
                continue
            total += 1
            value = parse_conf(line)
            if value is None:
                continue
            nv = normalize_conf(value)
            if nv:
                conf += 1
                if not value.startswith(CONF_PREFIXES):
                    normalized += 1
            else:
                bad.append(value)
    return {'total': total, 'conf': conf, 'bad': bad, 'normalized': normalized}

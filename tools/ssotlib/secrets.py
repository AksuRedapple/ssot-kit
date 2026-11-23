"""密钥形态识别与分级（唯一实现）。

为什么要有分级（2026-11-23 · 批次 5 P2）：
旧规则 `sk-[A-Za-z0-9_-]{20,}` / `sk-[0-9a-f]{5,31}` 没有词边界，
把 `task-<hex>` / `ask-at-poorest` / `hard-disk-<hex>` 的词尾当成密钥；
`sp_s0scrub --apply` 因此改写了 S0 原文语义（实测 S0 565 处疑似误报）。

三条判据：
  · high  ：有明确凭据前缀 + 词边界（不会被普通英文单词误伤），默认必清
  · medium：短 `sk-` 前缀 / Bearer，只有在 `api_key|token|secret|authorization…`
            80 字符上下文里才升级为 medium；默认清理
  · low   ：无上下文的短 `sk-<hex>`，只报告、不自动替换
"""
import hashlib
import re

REPLACEMENT = '[REDACTED-SECRET]'

HIGH = [
    ('sk_full', re.compile(r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}')),
    ('ghp', re.compile(r'(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{30,}')),
    ('github_pat', re.compile(r'(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{30,}')),
    ('akia', re.compile(r'(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}')),
    ('hf', re.compile(r'(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}')),
    ('pem', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
]
BEARER = re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._-]{30,}')
SK_SHORT = re.compile(r'(?<![A-Za-z0-9_-])sk-[0-9a-f]{5,31}(?![0-9a-f])')
CONTEXT = re.compile(r'(?i)(api[_-]?key|access[_-]?key|token|secret|authorization|bearer|password|passwd)')

# 便宜的前置过滤：只有命中这些字面量才值得跑完整 classify（5.8GB evidence 实测）
CANDIDATE = re.compile(
    r'(?i)(?<![A-Za-z0-9_-])sk-|ghp_|github_pat_|\bakia[0-9a-z]{16}|hf_|bearer\s|-----BEGIN ')

# 向后兼容：既有工具把 SECRET_RX 当 [(rx, rep)] 用来做 findall/隐私闸
SECRET_RX = [(rx, REPLACEMENT) for _name, rx in HIGH]


def _ctx(text, start, width=80):
    return text[max(0, start - width):start]


def hash8(value):
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _token(text, pos, maxlen=80, chars=None):
    j = pos
    n = len(text)
    while j < n and j - pos < maxlen and (
            (text[j].isalnum() or text[j] in '_-') if chars is None else text[j] in chars):
        j += 1
    return text[pos:j], j


def classify(text):
    """→ [{kind,start,end,value,confidence}]；O(n) 字面量查找，不做全量正则扫描。

    2026-11-23：267MB 转录上 8 条正则要 56s；改成 find + 小窗口后 <2s。
    """
    found = []

    def add(kind, start, end, conf):
        found.append({'kind': kind, 'start': start, 'end': end,
                      'value': text[start:end], 'confidence': conf})

    # sk-*（词边界；task-/disk-/risk- 不算）
    pos = 0
    while True:
        i = text.find('sk-', pos)
        if i < 0:
            break
        pos = i + 3
        if i > 0 and (text[i - 1].isalnum() or text[i - 1] in '_-'):
            continue
        tok, end = _token(text, i, 80)
        suf = tok[3:]
        if len(suf) >= 20:
            add('sk_full', i, end, 'high')
        elif 5 <= len(suf) <= 31 and all(c in '0123456789abcdef' for c in suf):
            conf = 'medium' if CONTEXT.search(_ctx(text, i)) else 'low'
            add('sk_short', i, end, conf)

    for name, prefix, minlen, chars in (
            ('ghp', 'ghp_', 30, None), ('github_pat', 'github_pat_', 30, None),
            ('hf', 'hf_', 30, None)):
        pos = 0
        while True:
            i = text.find(prefix, pos)
            if i < 0:
                break
            pos = i + len(prefix)
            if i > 0 and (text[i - 1].isalnum() or text[i - 1] == '_'):
                continue
            tok, end = _token(text, i, 120)
            if len(tok) - len(prefix) >= minlen:
                add(name, i, end, 'high')
    pos = 0
    while True:
        i = text.find('AKIA', pos)
        if i < 0:
            break
        pos = i + 4
        if i > 0 and text[i - 1].isalnum():
            continue
        tok, end = _token(text, i, 20)
        if len(tok) == 20 and all(c.isupper() or c.isdigit() for c in tok[4:]):
            add('akia', i, end, 'high')

    pos = 0
    while True:
        i = text.find('-----BEGIN ', pos)
        if i < 0:
            break
        pos = i + 10
        j = text.find('PRIVATE KEY-----', i, i + 90)
        if j >= 0:
            add('pem', i, j + len('PRIVATE KEY-----'), 'high')

    low = text.lower()
    pos = 0
    while True:
        i = low.find('bearer', pos)
        if i < 0:
            break
        pos = i + 6
        if i > 0 and (text[i - 1].isalnum() or text[i - 1] == '_'):
            continue
        j = i + 6
        while j < len(text) and text[j] in ' \t':
            j += 1
        tok, end = _token(text, j, 120, chars=set(
            'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-'))
        if len(tok) >= 30:
            # `Bearer <token>` 本身就是认证上下文；有 Authorization 时仍算 medium
            add('bearer', i, end, 'medium')

    # 去重叠：长匹配优先
    found.sort(key=lambda x: (x['start'], -(x['end'] - x['start'])))
    out, last_end = [], -1
    for f in found:
        if f['start'] >= last_end:
            out.append(f)
            last_end = f['end']
    return out


def _old_classify(text):
    """保留参考实现（仅测试对照用；不参与主路径）。"""

def scrub(text, level='medium', allowlist=None):
    """按置信度替换；level ∈ high|medium|all。allowlist 为 hash8 集合。"""
    if not text:
        return text or ''
    allow = set(allowlist or ())
    want = {'high'} if level == 'high' else (
        {'high', 'medium'} if level == 'medium' else {'high', 'medium', 'low'})
    out, pos = [], 0
    for f in classify(text):
        if f['confidence'] not in want:
            continue
        if allow and hash8(f['value']) in allow:
            continue
        out.append(text[pos:f['start']])
        out.append(REPLACEMENT)
        pos = f['end']
    out.append(text[pos:])
    return ''.join(out)


def counts(text):
    out = {'high': 0, 'medium': 0, 'low': 0}
    for f in classify(text):
        out[f['confidence']] += 1
    return out

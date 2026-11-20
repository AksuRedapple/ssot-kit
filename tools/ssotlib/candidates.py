"""候选命题的文本工具：归一化、指纹、分词、相似度、极性、句子切分。

这些是「候选抽取/去重/冲突判定」的共同底座；以前只在 sp_candidates.py 里，
其他工具要用只能把 600 行整器 import 进来。
"""
import hashlib
import re

NEG_RX = r'(禁止|不许|不要|不能|别|否决|无收益|不该|不需要|不必|无需|不用|并非|不代表|不允许|不应该|没被证明)'
POS_RX = r'(必须|应该|应当|需要|可以|能|允许|有收益|证明|确实|代表|足够|成功|就行|即可|等同于)'


def norm(s):
    s = s.lower()
    s = re.sub(r'\d+(\.\d+)?', '<n>', s)
    s = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def fp(s):
    return hashlib.sha1(norm(s).encode('utf-8')).hexdigest()[:16]


def tokens(s):
    """中文按 2-gram,英文按词——中文没有空格,按词切会退化成整句一个 token"""
    n = norm(s)
    out = set()
    cjk = re.findall(r'[\u4e00-\u9fff]', n)
    out.update(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    out.update(w for w in re.findall(r'[a-z0-9_]{2,}', n))
    return out


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap(a, b):
    """重叠系数:适合"同一件事换个说法"(jaccard 会被新增修饰语压低)"""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def polarity(s):
    """先判否定:否定词常包含肯定词(如"不需要"含"需要"),同时计分会互相抵消 → 必须先否后肯。"""
    if re.search(NEG_RX, s):
        return -1
    if re.search(POS_RX, s):
        return +1
    return 0


def clean_claim(s):
    s = re.sub(r'^\s*(?:[-*+]|\d+[.)])\s*', '', s)
    s = re.sub(r'\*\*|__|`', '', s)
    return s.strip(' -—:：,，')


def rstrip_lines(s):
    return '\n'.join(line.rstrip() for line in str(s or '').splitlines())


def is_junk(s):
    if re.match(r'^\s*\|', s) or s.count('|') >= 3:
        return True
    if re.match(r'^\s*(道具|图示|表格|注[:：])', s):
        return True
    core = clean_claim(s)
    if len(core) < 12 or len(core) > 200:
        return True
    # 纯枚举/纯列表项(无谓语标记)不要
    if not re.search(r'[。；:：]|是|为|要|需|应|必须|禁|不|＝|=', core):
        return True
    return False


def sentences(text):
    for part in re.split(r'(?<=[。！？\n])', text or ''):
        p = part.strip()
        if 8 <= len(p) <= 220:
            yield p

"""文本切块：按目标长度累积、硬上限再切（索引与断言审计共用）。"""


def chunk_file(path, target=700, hard=1400):
    lines = open(path, errors='replace').read().splitlines()
    chunks, cur, start = [], [], 1
    for i, l in enumerate(lines, 1):
        if not cur:
            start = i
        cur.append(l)
        if len('\n'.join(cur)) >= target:
            chunks.append((start, '\n'.join(cur)))
            cur = []
    if cur:
        chunks.append((start, '\n'.join(cur)))
    out = []
    for s, t in chunks:
        while len(t) > hard:
            out.append((s, t[:hard], '', ''))
            t = t[hard:]
        if t.strip():
            out.append((s, t, '', ''))
    return out

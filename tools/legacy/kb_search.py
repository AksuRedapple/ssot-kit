#!/usr/bin/env python3
"""kb_search · 知识库语义检索（配套 kb_index.py）

用法:
  python3 kb_search.py "查询词句" [--top 8] [--root ~/ssot] [--db PATH] [--api URL]

原理：查询与文档用 EmbeddingGemma 建议前缀配对，L2 归一化后点积=余弦。
纯标准库（无第三方依赖）；工作机规模（数千块内）下检索 ~1s 级。
"""
import argparse
import datetime
import json
import math
import os
import sqlite3
import struct
import sys
import urllib.request

QUERY_PREFIX = 'task: search result | query: '


def embed(api, text, timeout=60):
    req = urllib.request.Request(
        api,
        data=json.dumps({'input': [text]}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())['data'][0]['embedding']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query')
    ap.add_argument('--top', type=int, default=8)
    ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    ap.add_argument('--db', default='')
    ap.add_argument('--api', default='http://127.0.0.1:8399/v1/embeddings')
    a = ap.parse_args()

    db = a.db or os.path.join(a.root, 'kb-index', 'kb.db')
    if not os.path.exists(db):
        print('❌ 无索引——先跑: python3 ~/ssot/tools/kb_index.py')
        sys.exit(1)

    try:
        qv = embed(a.api, QUERY_PREFIX + a.query)
    except Exception as e:
        print(f'❌ 嵌入服务未响应（{e}）\n   先跑: bash ~/ssot/tools/serve_embed.sh')
        sys.exit(1)
    n = math.sqrt(sum(x * x for x in qv)) or 1.0
    qv = [x / n for x in qv]

    con = sqlite3.connect(db)
    best = []
    for path, line, text, blob in con.execute('select path,line,text,vec from chunks'):
        v = struct.unpack(f'<{len(blob) // 4}f', blob)
        s = 0.0
        for x, y in zip(qv, v):
            s += x * y
        best.append((s, path, line, text))
    best.sort(key=lambda r: r[0], reverse=True)

    # 留痕：用数据回答「到底有没有在主动用」（时间 + query + 命中数）
    try:
        log = os.path.join(os.path.dirname(db), 'search-log.tsv')
        q = ' '.join(a.query.split())
        with open(log, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\t{q}\t{min(a.top, len(best))}\n')
    except Exception:
        pass

    if not best:
        print('（索引为空）')
        return
    for s, path, line, text in best[:a.top]:
        snippet = ' '.join(text.split())[:150]
        print(f'{s:.3f}  {path}:{line}\n       {snippet}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""kb_index · 本机知识库语义索引（EmbeddingGemma via llama-server /v1/embeddings）

用法:
  python3 kb_index.py [--root ~/ssot] [--db PATH] [--api URL] [--full]

- 语料 = root 下全部 .md（排除 .index/ models/ .git/ __pycache__/ compile/）
- 排除清单：root/.kbignore（一行一 pattern，# 注释，fnmatch 语义，相对 root）
- 增量：按文件 md5 判变，只重嵌变化文件的块
- 超长行硬切（防嵌入请求超限）；批量嵌入失败拆批重试，单块失败计数跳过
- 向量 L2 归一化后存 sqlite BLOB(float32)；纯标准库（无第三方依赖）
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import re
import sqlite3
import struct
import subprocess
import sys
import urllib.request

DOC_PREFIX = 'title: none | text: '
SECRET_RX = re.compile(
    r'(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|'
    r'hf_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def md5(s):
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def git_commit(root):
    try:
        return subprocess.check_output(['git', '-C', root, 'rev-parse', '--short', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL).strip() or '-'
    except Exception:
        return '-'


def write_build(root, db, chunks):
    try:
        data = {'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                'commit': git_commit(root), 'chunks': chunks, 'root': root}
        with open(os.path.join(os.path.dirname(db), 'BUILD.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except Exception:
        pass


def chunks_of(path, target=700, max_len=1600):
    """按行聚块（~target 字符/块）；超长行硬切 max_len（防嵌入请求超限）。"""
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except Exception:
        return []
    out, cur, start, size = [], [], 1, 0
    for i, ln in enumerate(lines, 1):
        # 超长行：先冲掉累计块，再按 max_len 硬切
        while len(ln) > max_len:
            if cur:
                out.append((start, '\n'.join(cur)))
                cur, start, size = [], i, 0
            out.append((i, ln[:max_len]))
            ln = ln[max_len:]
        if not ln:
            continue
        if not cur:
            start = i
        cur.append(ln)
        size += len(ln) + 1
        if size >= target:
            out.append((start, '\n'.join(cur)))
            cur, start, size = [], i + 1, 0
    if cur:
        out.append((start, '\n'.join(cur)))
    return out


def embed_batch(api, texts, timeout=300):
    req = urllib.request.Request(
        api,
        data=json.dumps({'input': texts}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return [d['embedding'] for d in data['data']]


def embed_robust(api, batch, timeout=300):
    """批失败拆半重试；单块仍失败则返回 None（由主循环计数跳过）。"""
    try:
        return embed_batch(api, batch, timeout)
    except Exception as e:
        if len(batch) == 1:
            print(f'  ⚠️ 跳过 1 块：{e}', file=sys.stderr)
            return [None]
        mid = len(batch) // 2
        return embed_robust(api, batch[:mid], timeout) + embed_robust(api, batch[mid:], timeout)


def norm(v):
    import math
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    ap.add_argument('--db', default='')
    ap.add_argument('--api', default='http://127.0.0.1:8399/v1/embeddings')
    ap.add_argument('--full', action='store_true', help='全量重建')
    ap.add_argument('--batch', type=int, default=16)
    a = ap.parse_args()

    db = a.db or os.path.join(a.root, 'kb-index', 'kb.db')
    os.makedirs(os.path.dirname(db), exist_ok=True)

    # 服务探测（失败快速报错，不静默）
    try:
        embed_batch(a.api, ['ping'], timeout=10)
    except Exception as e:
        print(f'❌ 嵌入服务未响应（{e}）\n   先跑: bash ~/ssot/tools/serve_embed.sh')
        sys.exit(1)

    ignore = []
    ip = os.path.join(a.root, '.kbignore')
    if os.path.exists(ip):
        ignore = [l.strip() for l in open(ip, encoding='utf-8')
                  if l.strip() and not l.strip().startswith('#')]

    con = sqlite3.connect(db)
    con.execute('create table if not exists files(path text primary key, md5 text)')
    con.execute('create table if not exists chunks(path text, line int, text text, vec blob)')
    con.execute('create index if not exists i_chunks_path on chunks(path)')

    def gen():
        for dp, dns, fns in os.walk(a.root):
            dns[:] = [d for d in dns if d not in ('.index', 'models', '.git', '__pycache__',
                                                    'compile', '_pending', '.draft-state')]
            for fn in sorted(fns):
                if not fn.endswith('.md'):
                    continue
                rel = os.path.relpath(os.path.join(dp, fn), a.root).replace(os.sep, '/')
                if any(fnmatch.fnmatch(rel, pat) for pat in ignore):
                    continue
                yield os.path.join(dp, fn)

    todo, current, secret_skipped = [], set(), 0
    for p in gen():
        try:
            raw = open(p, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        rel = os.path.relpath(p, a.root)
        if SECRET_RX.search(raw):
            secret_skipped += 1
            print(f'  🔒 跳过（密钥形态）: {rel}', file=sys.stderr)
            continue
        h = md5(raw)
        current.add(rel)
        row = con.execute('select md5 from files where path=?', (rel,)).fetchone()
        if row and row[0] == h and not a.full:
            continue
        todo.append((p, rel, h))

    # 排除目录/.kbignore 变更后的孤儿清理：从索引移除已不在语料里的路径
    existing = {r[0] for r in con.execute('select path from files').fetchall()}
    for rel in existing - current:
        con.execute('delete from chunks where path=?', (rel,))
        con.execute('delete from files where path=?', (rel,))
    con.commit()

    if not todo:
        write_build(a.root, db, con.execute('select count(*) from chunks').fetchone()[0])
        extra = f'（🔒 {secret_skipped} 文件跳过）' if secret_skipped else ''
        print(f'✅ 无变更，索引已是最新{extra}')
        return

    total = skipped = 0
    for p, rel, h in todo:
        blocks = chunks_of(p)
        con.execute('delete from chunks where path=?', (rel,))
        texts = [DOC_PREFIX + t for _, t in blocks]
        vecs = []
        for i in range(0, len(texts), a.batch):
            vecs += embed_robust(a.api, texts[i:i + a.batch])
            print(f'  {rel}: {min(i + a.batch, len(texts))}/{len(texts)}', file=sys.stderr)
        file_skipped = 0
        for (ln, t), v in zip(blocks, vecs):
            if v is None:
                file_skipped += 1
                continue
            con.execute('insert into chunks(path,line,text,vec) values(?,?,?,?)',
                        (rel, ln, t[:2000], struct.pack(f'<{len(v)}f', *norm(v))))
        # 有跳过块时不记 md5，下轮增量会重试（避免静默永久缺口）
        if file_skipped == 0:
            con.execute('insert or replace into files(path,md5) values(?,?)', (rel, h))
        else:
            con.execute('delete from files where path=?', (rel,))
            print(f'  ⚠️ {rel}: {file_skipped} 块跳过，下轮重试', file=sys.stderr)
        con.commit()
        total += len(blocks) - file_skipped
        skipped += file_skipped

    write_build(a.root, db, con.execute('select count(*) from chunks').fetchone()[0])
    tail = f'（⚠️ {skipped} 块跳过）' if skipped else ''
    if secret_skipped:
        tail += f'（🔒 {secret_skipped} 文件因密钥形态跳过）'
    print(f'✅ 索引完成：{len(todo)} 个文件 / {total} 块{tail} → {db}')


if __name__ == '__main__':
    main()

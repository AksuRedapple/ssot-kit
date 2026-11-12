#!/usr/bin/env python3
"""sp_index · SSOT 语义索引器 v4（EmbeddingGemma 2 via llama-server:8399）

v3（2026-10-14）：transcript.jsonl 全文 / 轮切块+语境头 / role·ts / 闲聊过滤。
v4（2026-10-15）：**增量模式** `--incremental`
  - src_state(path,digest) 摘要表：按源文件 md5 判变——变的源先删旧块再重嵌，未变不动
  - 首次增量（无 src_state）：bootstrap——以 index.db mtime 为界，更晚的源补嵌，其余仅记摘要
  - 全量模式亦写 src_state（此后增量可用；全量仍会清库重建）
v4.1（2026-11-04）：摘要口径收窄——会话指纹 = jsonl md5 + meta 进块字段（title 48 字 + start 日期）。
  meta 的 schema 等非进块字段不再触发重嵌（A531）；`--restamp` 一次性迁移 src_state（只改摘要不重嵌）。
用法：python3 sp_index.py [--incremental|--restamp] [--allow-secret-files]
                        [--no-pack] [--full-pack] [--pack-only] [--no-wait] [--wait-timeout 秒]
                        （需 llama-server:8399 在跑）
--no-pack     只更新 index.db，不重建 950MB 向量包（语义检索会暂时看不到新内容）
--full-pack   强制全量重建向量包（默认增量追加，stale 过多才压实）
--pack-only   只重建向量包，不重嵌
--no-wait     锁被占用时立即退出（退出码 3）
--wait-timeout 等锁上限，默认 1800s
隐私闸：源文本命中完整密钥形态时拒绝索引（先脱敏）；仅确认为文档示例时才可加 --allow-secret-files。
"""
import glob
import fcntl
import hashlib
import json
import datetime
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.request

SSOT = os.path.expanduser('~/ssot')
SEM = os.path.join(SSOT, 'S2-index', 'semantic')
DB = os.path.join(SEM, 'index.db')          # legacy（v1 单库）；版本化后仅作兜底
VERS = os.path.join(SEM, 'versions')        # 每个全量构建一个版本目录
ACTIVE = os.path.join(SEM, 'active.json')   # 唯一在线指针（原子切换）


def active_version():
    """读 active.json；指向的版本不存在就当没有（回退 legacy）。"""
    try:
        v = json.load(open(ACTIVE, encoding='utf-8')).get('version')
        if v and os.path.exists(os.path.join(VERS, v, 'index.db')):
            return v
    except Exception:
        pass
    return None


def resolve_db():
    v = active_version()
    return os.path.join(VERS, v, 'index.db') if v else DB


def list_versions():
    out = []
    if os.path.isdir(VERS):
        for name in sorted(os.listdir(VERS)):
            d = os.path.join(VERS, name)
            if not os.path.isdir(d):
                continue
            try:
                n = sqlite3.connect(os.path.join(d, 'index.db'), timeout=5).execute(
                    'select count(*) from chunks').fetchone()[0]
            except Exception:
                n = -1
            st = 'building' if name.endswith('.building') else 'ready'
            try:
                st = open(os.path.join(d, 'STATUS'), encoding='utf-8').read().strip() or st
            except Exception:
                pass
            out.append((name, st, n, os.path.getmtime(d)))
    return out


def write_root_manifest(ver):
    """根 BUILD.json = 在线清单（daemon 盯它的 mtime 决定 reload）。"""
    src = os.path.join(VERS, ver, 'BUILD.json')
    data = {}
    try:
        data = json.load(open(src, encoding='utf-8'))
    except Exception:
        pass
    data.update({'active': ver, 'db': os.path.join('versions', ver, 'index.db'),
                 'activated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
    tmp = os.path.join(SEM, '.BUILD.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, os.path.join(SEM, 'BUILD.json'))


def set_active(ver):
    tmp = os.path.join(SEM, '.active.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'version': ver, 'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')},
                  f, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, ACTIVE)          # POSIX 原子
    try:
        open(os.path.join(VERS, ver, 'STATUS'), 'w', encoding='utf-8').write('active\n')
    except Exception:
        pass
    for name, st, _n, _m in list_versions():
        if name != ver and st == 'active':
            try:
                open(os.path.join(VERS, name, 'STATUS'), 'w', encoding='utf-8').write('retired\n')
            except Exception:
                pass
    write_root_manifest(ver)


def prune_versions(keep=2):
    """保留最近 keep 个 ready 版本（active 永远保留）+ 清掉 >7 天的 retired。"""
    # 顺手清掉中断留下的 .building（超过 1 天的），它们是构建残骸不是版本
    for name, st, _n, m in list_versions():
        if name.endswith('.building') and (time.time() - m) > 86400:
            shutil.rmtree(os.path.join(VERS, name), ignore_errors=True)
    vs = [v for v in list_versions() if v[1] != 'building']
    vs.sort(key=lambda x: x[3], reverse=True)
    act = active_version()
    removed = []
    for i, (name, st, _n, m) in enumerate(vs):
        if name == act:
            continue
        if i < keep and (time.time() - m) < 7 * 86400:
            continue
        shutil.rmtree(os.path.join(VERS, name), ignore_errors=True)
        removed.append(name)
    return removed
API = 'http://127.0.0.1:8399/v1/embeddings'
DOC_PREFIX = 'title: none | text: '
BATCH = 32

# --- 分片/自定义库(2026-10-25,为多进程并建+合并而加;不影响默认行为) ---
_shard = None
for _a in sys.argv:
    if _a.startswith('--db='):
        DB = _a.split('=', 1)[1]
    elif _a.startswith('--shard='):
        _i, _n = _a.split('=', 1)[1].split('/')
        _shard = (int(_i), int(_n))

GREET_RX = re.compile(
    r'^(你好|您好|hi|hello|在吗|在么|早上好|晚安|谢谢|多谢|好的|嗯+|ok)[!！。.~？?\s]*$', re.I)
SECRET_RX = re.compile(
    r'(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|'
    r'hf_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')

# v5（2026-10-15）：①tool_use 选择性入索引（动作/语义类工具，滤 Read/Grep/任务板噪音）
#                 ②子 agent 派生层 S1-subagents 入索引（A 档 md + B 档 jsonl）
TOOL_IDX = {'Bash', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'Agent',
            'WebFetch', 'WebSearch', 'Skill'}
S1VER = 'v5'  # 切块器版本：变更即全量重嵌（摘要以 版本+md5 计）


def md5_files(*paths):
    h = hashlib.md5()
    for p in paths:
        with open(p, 'rb') as f:
            for c in iter(lambda: f.read(1 << 20), b''):
                h.update(c)
    return h.hexdigest()


def meta_chunk_fields(mj):
    """meta 里真正进块文本的字段：title（截 48）+ start 日期（截 10）。

    摘要只认这些内容字段；schema 等非进块字段不参与指纹（A531：
    否则 m0002 这类整库盖章会让全部会话判变、白跑一次全量重嵌）。
    """
    try:
        d = json.load(open(mj, encoding='utf-8'))
        return ((d.get('title') or '')[:48] + '\x1f' + (d.get('start') or '')[:10]).encode()
    except Exception:
        return b''


def refresh_pack():
    """索引写完后刷新向量包（sp_semantic 快查用；失败不影响索引主流程）。
    分片/自定义库模式跳过——否则 N 个 shard 会互相覆盖同一份 pack。"""
    if _shard or '--db=' in ' '.join(sys.argv):
        print('向量包: 跳过（分片模式，合并后由主库重建）', flush=True)
        return
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        if '--full-pack' in sys.argv:
            from sp_semantic import build_pack
            n, secs = build_pack()
            print(f'向量包: 全量重建 {n} 行（{secs:.0f}s）', flush=True)
            return
        from sp_semantic import build_pack_incremental
        r = build_pack_incremental()
        if r['mode'] == 'noop':
            print(f'向量包: 已最新（{r["stale"]} 行待压实）', flush=True)
        elif r['mode'] == 'append':
            print(f'向量包: 增量追加 {r["appended"]} 行（{r["secs"]:.0f}s，stale {r["stale"]}）', flush=True)
        else:
            print(f'向量包: 全量压实 {r["n"]} 行（{r["secs"]:.0f}s）', flush=True)
    except Exception as e:  # noqa: BLE001
        print(f'向量包: 跳过（{e}）', flush=True)


def git_commit():
    try:
        return subprocess.check_output(['git', '-C', SSOT, 'rev-parse', '--short', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL).strip() or '-'
    except Exception:
        return '-'


def contract_schema():
    """实例契约号（profile/contract.json）；无契约文件→None（旧实例不盖章）。"""
    try:
        d = json.load(open(os.path.join(SSOT, 'profile', 'contract.json'), encoding='utf-8'))
        return int(d.get('contract', 0)) or None
    except Exception:
        return None


def write_build():
    """索引新鲜度戳：commit + 块数 + 生成时间 + 契约 schema（供 sp_semantic/ssot_check/SSOT_REPORT 读）。

    schema 必须由生成器自己盖（契约 v2 · m0002 的章会被下次重建抹掉，见 A530）。
    """
    try:
        con = sqlite3.connect(DB, timeout=30)
        n = con.execute('select count(*) from chunks').fetchone()[0]
        con.close()
    except Exception:
        n = 0
    data = {'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'commit': git_commit(), 'chunks': n, 'root': SSOT}
    schema = contract_schema()
    if schema:
        data['schema'] = schema
    try:
        with open(os.path.join(os.path.dirname(DB), 'BUILD.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
    except Exception:
        pass


def file_corpus_files():
    fs = []
    fs += [os.path.join(SSOT, 'START.md'), os.path.join(SSOT, 'GUIDE.md')]
    fs += sorted(glob.glob(os.path.join(SSOT, 'profile', '*.md')))
    fs += sorted(glob.glob(os.path.join(SSOT, 'lines', '*.md')))
    fs += sorted(glob.glob(os.path.join(SSOT, 'knowledge', '*.md')))
    fs += sorted(glob.glob(os.path.join(SSOT, 'knowledge', 'topics', '*.md')))
    fs += [os.path.join(SSOT, 'sessions', 'registry.md')]
    fs += sorted(glob.glob(os.path.join(SSOT, 'inbox', '*.md')))
    return [f for f in fs if os.path.isfile(f)]


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


def file_groups():
    groups = []
    for f in file_corpus_files():
        chunks = chunk_file(f)
        if not chunks:
            continue
        groups.append((os.path.relpath(f, SSOT), md5_files(f), chunks))
    return groups


def s1_groups():
    """→ [(rel, digest, [(line, text, role, ts)])]；切块规则同 v3"""
    groups = []
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions'))):
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            jl = os.path.join(d, 'transcript.jsonl')
            mj = os.path.join(d, 'meta.json')
            if not os.path.isfile(jl):
                continue
            meta = {}
            try:
                meta = json.loads(open(mj).read())
            except Exception:
                pass
            title = (meta.get('title') or '')[:48]
            date = (meta.get('start') or '')[:10]
            rows = []
            for i, ln in enumerate(open(jl, errors='replace'), 1):
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                kind = o.get('kind')
                if kind not in ('text', 'compact_summary', 'tool_result', 'tool_use'):
                    continue
                if kind == 'tool_use':
                    for t in (o.get('tools') or []):
                        nm = t.get('name')
                        br = (t.get('brief') or '').strip()
                        if nm in TOOL_IDX and br:
                            rows.append((i, f'[会话: {title} · {date} · 工具调用]\n{nm}: {br}',
                                         'tool', (o.get('t') or '')[:19]))
                    continue
                txt = (o.get('content') or '').strip()
                if not txt:
                    continue
                role = o.get('role') or ''
                if role == 'user' and (len(txt) < 8 or GREET_RX.match(txt)):
                    continue
                label = '用户' if role == 'user' else ('助手' if role == 'assistant' else role)
                head = f'[会话: {title} · {date} · {label}]'
                ts = (o.get('t') or '')[:19]
                if len(txt) <= 1500:
                    rows.append((i, f'{head}\n{txt}', role, ts))
                else:
                    for k in range(0, len(txt), 1500):
                        rows.append((i, f'{head}\n{txt[k:k + 1500]}', role, ts))
            if rows:
                # 指纹只含进块内容：jsonl + meta 的 title/start；schema 等不进（A531）
                digest = (S1VER + ':' + md5_files(jl) + ':'
                          + hashlib.md5(meta_chunk_fields(mj)).hexdigest())
                groups.append((os.path.relpath(jl, SSOT), digest, rows))
    return groups


def sa_groups():
    """子 agent 派生层（S1-subagents）：A 档 subagents.md + B 档 <stem>.jsonl"""
    groups = []
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-subagents'))):
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            if not os.path.isdir(d):
                continue
            pdir = os.path.basename(d)
            smd = os.path.join(d, 'subagents.md')
            if os.path.isfile(smd):
                chunks = chunk_file(smd)
                if chunks:
                    groups.append((os.path.relpath(smd, SSOT), S1VER + ':' + md5_files(smd), chunks))
            for jf in sorted(glob.glob(os.path.join(d, '*.jsonl'))):
                stem = os.path.basename(jf)[:-6]
                head_base = f'[子agent: {pdir[:64]} · {stem[:26]}]'
                rows = []
                for i, ln in enumerate(open(jf, errors='replace'), 1):
                    try:
                        o = json.loads(ln)
                    except Exception:
                        continue
                    kind = o.get('kind')
                    if kind not in ('text', 'tool_result', 'tool_use'):
                        continue
                    ts = (o.get('t') or '')[:19]
                    role = o.get('role') or ''
                    if kind == 'tool_use':
                        for t in (o.get('tools') or []):
                            nm = t.get('name')
                            br = (t.get('brief') or '').strip()
                            if nm in TOOL_IDX and br:
                                rows.append((i, f'{head_base}\n工具调用 {nm}: {br}', 'tool', ts))
                        continue
                    txt = (o.get('content') or '').strip()
                    if not txt:
                        continue
                    if role == 'user' and kind == 'text' and (len(txt) < 8 or GREET_RX.match(txt)):
                        continue
                    label = '用户' if role == 'user' else ('助手' if role == 'assistant' else role)
                    head = f'{head_base} · {label}'
                    if len(txt) <= 1500:
                        rows.append((i, f'{head}\n{txt}', role, ts))
                    else:
                        for k in range(0, len(txt), 1500):
                            rows.append((i, f'{head}\n{txt[k:k + 1500]}', role, ts))
                if rows:
                    groups.append((os.path.relpath(jf, SSOT), S1VER + ':' + md5_files(jf), rows))
    return groups


def embed_batch(texts, timeout=300):
    req = urllib.request.Request(
        API,
        data=json.dumps({'input': texts}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return [x['embedding'] for x in d['data']]


def pack_norm(vec):
    import math
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return struct.pack(f'<{len(vec)}f', *[x / n for x in vec])


def embed_and_store(con, todo, blocks, t0):
    flat = [(g, r) for g in todo for r in blocks[g]]
    if flat:
        for i in range(0, len(flat), BATCH):
            batch = flat[i:i + BATCH]
            vecs = embed_batch([DOC_PREFIX + b[1][1] for b in batch])
            con.executemany(
                'insert into chunks(path,line,text,role,ts,vec) values(?,?,?,?,?,?)',
                [(b[0], b[1][0], b[1][1], b[1][2], b[1][3], pack_norm(v))
                 for b, v in zip(batch, vecs)])
            con.commit()
            if (i // BATCH) % 25 == 0:
                print(f'  {i + len(batch)}/{len(flat)}  {time.time() - t0:.0f}s', flush=True)
    return len(flat)


def embed_and_store_diff(con, todo, blocks, old_rows, t0):
    """块级 diff：同 (text, role, ts) 复用旧向量，只嵌新块。

    old_rows: {path: [(line,text,role,ts,vec)]}；行号变化不影响复用。
    返回 (embedded, reused)。
    """
    flat, reused_rows = [], []
    for g in todo:
        pool = {}
        for _line, text, role, ts, vec in old_rows.get(g, []):
            if vec:
                pool.setdefault((text, role, ts), []).append(vec)
        for r in blocks[g]:
            key = (r[1], r[2], r[3])
            bucket = pool.get(key)
            if bucket:
                reused_rows.append((g, r[0], r[1], r[2], r[3], bucket.pop()))
            else:
                flat.append((g, r))
    if reused_rows:
        con.executemany(
            'insert into chunks(path,line,text,role,ts,vec) values(?,?,?,?,?,?)',
            reused_rows)
        con.commit()
    if flat:
        for i in range(0, len(flat), BATCH):
            batch = flat[i:i + BATCH]
            vecs = embed_batch([DOC_PREFIX + b[1][1] for b in batch])
            con.executemany(
                'insert into chunks(path,line,text,role,ts,vec) values(?,?,?,?,?,?)',
                [(b[0], b[1][0], b[1][1], b[1][2], b[1][3], pack_norm(v))
                 for b, v in zip(batch, vecs)])
            con.commit()
            if (i // BATCH) % 25 == 0:
                print(f'  新嵌 {i + len(batch)}/{len(flat)}  {time.time() - t0:.0f}s', flush=True)
    return len(flat), len(reused_rows)


FTS_SQL = [
    "create virtual table if not exists chunks_fts using fts5(text, path unindexed, "
    "content='chunks', content_rowid='id', tokenize='trigram')",
    "create trigger if not exists chunks_ai after insert on chunks begin "
    "insert into chunks_fts(rowid,text,path) values (new.id,new.text,new.path); end",
    "create trigger if not exists chunks_ad after delete on chunks begin "
    "insert into chunks_fts(chunks_fts,rowid,text,path) values('delete',old.id,old.text,old.path); end",
    "create trigger if not exists chunks_au after update on chunks begin "
    "insert into chunks_fts(chunks_fts,rowid,text,path) values('delete',old.id,old.text,old.path); "
    "insert into chunks_fts(rowid,text,path) values (new.id,new.text,new.path); end",
]


def ensure_fts(con, rebuild=False):
    """FTS5 trigram（中文 3-gram）；外部内容表 + 触发器保持增量同步。"""
    existed = con.execute("select name from sqlite_master where name='chunks_fts'").fetchone()
    for sql in FTS_SQL:
        con.execute(sql)
    # 2026-11-06：id 覆盖索引。chunks 行里带 1.9GB 的 vec BLOB，
    # 直接 `select id from chunks` 会扫到 BLOB 页（实测 40s）；有了这个索引
    # 只扫 ~2.5MB 的 id b-tree（实测 0.3s），增量 pack 的 missing 计算才可用。
    con.execute('create index if not exists chunks_id_only on chunks(id)')
    # 2026-11-06：path 索引。增量按源删旧块是 `delete from chunks where path=?`；
    # 没有索引时每个变更源都全表扫 1.9GB（89 源实测 30min 未完成）。
    con.execute('create index if not exists chunks_path_idx on chunks(path)')
    if rebuild or not existed:
        con.execute("insert into chunks_fts(chunks_fts) values('rebuild')")


def _try_lock(fd):
    """拿实例锁；被占用时打印持有者并每 30s 报一次进度，可超时/不等待。"""
    lock_path = os.path.join(os.path.dirname(DB), '.lock')

    def holder():
        try:
            d = json.loads(open(lock_path, encoding='utf-8').read() or '{}')
            pid = d.get('pid', '?')
            started = float(d.get('started', 0) or 0)
            age = f'，已运行 {time.time() - started:.0f}s' if started else ''
            return f'pid={pid}{age}'
        except Exception:
            return '持有者未知'

    def stamp():
        try:
            with open(lock_path, 'w', encoding='utf-8') as f:
                json.dump({'pid': os.getpid(), 'started': time.time(),
                           'argv': ' '.join(sys.argv)}, f)
        except Exception:
            pass

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp()
        return True
    except OSError:
        no_wait = '--no-wait' in sys.argv
        timeout = 1800.0
        for i, a in enumerate(sys.argv):
            if a == '--wait-timeout' and i + 1 < len(sys.argv):
                try:
                    timeout = float(sys.argv[i + 1])
                except ValueError:
                    pass
            elif a.startswith('--wait-timeout='):
                try:
                    timeout = float(a.split('=', 1)[1])
                except ValueError:
                    pass
        print(f'另一实例在跑（{holder()}），等待其完成…', flush=True)
        if no_wait:
            print('❌ --no-wait：未拿到索引锁，退出', flush=True)
            return False
        t_wait = time.time()
        last = 0.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                stamp()
                print(f'✅ 拿到索引锁（等待 {time.time() - t_wait:.0f}s），继续', flush=True)
                return True
            except OSError:
                elapsed = time.time() - t_wait
                if elapsed >= timeout:
                    print(f'❌ 等锁超时（{timeout:.0f}s，{holder()}），退出；可加 --no-wait 或稍后重跑', flush=True)
                    return False
                if elapsed - last >= 30:
                    print(f'  仍在等待索引锁 {elapsed:.0f}s（{holder()}）', flush=True)
                    last = elapsed
                time.sleep(1)


def main():
    global DB
    if '--status' in sys.argv:
        # 只读：放在实例锁之前，构建进行中也能查版本与块数
        print("active: %s" % (active_version() or '(legacy index.db)'))
        print("db    : %s" % resolve_db())
        for name, st, n, m in list_versions():
            print("  %-30s %-10s chunks=%-7s %s" % (
                name, st, n, datetime.datetime.fromtimestamp(m).strftime('%m-%d %H:%M')))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_contract import guard as _contract_guard
    if not _contract_guard('sp_index', write=True):
        return 2
    # 实例锁（2026-10-15）：增量/全量互斥——防 launchd 值守与手动跑并发双写（曾致重复块，见当日去重记录）
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    lock_fd = os.open(os.path.join(os.path.dirname(DB), '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    if not _try_lock(lock_fd):
        return 3
    t0 = time.time()
    args = sys.argv[1:]

    def _fmt_ver(row):
        name, st, n, m = row
        return "  %-30s %-10s chunks=%-7s %s" % (
            name, st, n, datetime.datetime.fromtimestamp(m).strftime('%m-%d %H:%M'))

    if '--adopt' in args:
        # 把 legacy 单库收编成第一个版本（同盘 rename，秒级；失败不动原库）
        if active_version():
            sys.exit('已有 active 版本，无需 adopt')
        if not os.path.exists(DB):
            sys.exit('没有可收编的 legacy index.db')
        ts = datetime.datetime.now().strftime('%Y%m%dT%H%M')
        ver = '%s-%s' % (ts, ((git_commit() or '-').strip('-') or 'nogit')[:8])
        vdir = os.path.join(VERS, ver)
        os.makedirs(vdir, exist_ok=True)
        for f in ('index.db', 'pack-vecs.f32', 'pack-ids.i64'):
            src = os.path.join(SEM, f)
            if os.path.exists(src):
                os.replace(src, os.path.join(vdir, f))
        write_build_in = os.path.join(vdir, 'BUILD.json')
        try:
            data = json.load(open(os.path.join(SEM, 'BUILD.json'), encoding='utf-8'))
        except Exception:
            data = {}
        data['adopted_at'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        json.dump(data, open(write_build_in, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        open(os.path.join(vdir, 'STATUS'), 'w', encoding='utf-8').write('ready\n')
        set_active(ver)
        print('✅ adopt：%s → versions/%s（active 已切换）' % ('legacy index.db', ver))
        return 0

    if '--activate' in args:
        i = args.index('--activate')
        want = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith('--') else None
        vers = [v for v in list_versions() if v[1] != 'building']
        if not vers:
            sys.exit('没有可激活的版本')
        if want:
            if want not in [v[0] for v in vers]:
                sys.exit('版本不存在：%s' % want)
            ver = want
        else:
            ver = sorted(vers, key=lambda x: x[3])[-1][0]
        set_active(ver)
        print('✅ activate：%s' % ver)
        return 0

    if '--rollback' in args:
        act = active_version()
        vers = sorted([v for v in list_versions() if v[1] != 'building'], key=lambda x: x[3])
        prev = None
        for name, _st, _n, _m in vers:
            if name == act:
                break
            prev = name
        if not prev:
            sys.exit('没有上一版可回滚')
        set_active(prev)
        print('✅ rollback：%s → %s' % (act, prev))
        return 0

    if '--prune' in args:
        removed = prune_versions(keep=2)
        print('✅ prune：移除 %d 版%s' % (len(removed), ('（%s）' % '、'.join(removed)) if removed else ''))
        return 0

    build_dir = None
    if '--build' in args or '--full' in args:
        ts = datetime.datetime.now().strftime('%Y%m%dT%H%M')
        build_dir = os.path.join(VERS, '%s-%s.building' % (ts, ((git_commit() or '-').strip('-') or 'nogit')[:8]))
        os.makedirs(build_dir, exist_ok=True)
        DB = os.path.join(build_dir, 'index.db')
        print('构建目录：%s（线上 active 不动）' % build_dir, flush=True)
    else:
        DB = resolve_db()

    if '--pack-only' in sys.argv:
        if not os.path.exists(DB):
            sys.exit('索引不存在——先跑全量')
        refresh_pack()
        write_build()
        return
    if '--fts-only' in sys.argv:
        if not os.path.exists(DB):
            sys.exit('索引不存在——先跑全量')
        con = sqlite3.connect(DB, timeout=30)
        ensure_fts(con, rebuild=True)
        con.commit()
        con.close()
        write_build()
        print('✅ FTS trigram 重建完成')
        return
    inc = ('--incremental' in args) or not ('--build' in args or '--full' in args)
    fg = file_groups()
    sg = s1_groups()
    sas = sa_groups()
    groups = fg + sg + sas
    if _shard:
        _i, _n = _shard
        groups = groups[_i::_n]
        print(f'分片 {_i}/{_n}:{len(groups)} 组', flush=True)
    digests = {g[0]: g[1] for g in groups}
    blocks = {g[0]: g[2] for g in groups}
    if '--restamp' in sys.argv:
        # 一次性口径迁移（2026-11-04）：摘要收窄后，旧 src_state 会全部判变、再跑一次全量重嵌。
        # 本模式只重写摘要、不重嵌。安全判据：仅当 prev 等于「按当前文件算的旧口径摘要」才改写
        # ——证明差异只来自口径；内容真变过的源保持不动，交给下一次 --incremental 重嵌。
        if not os.path.exists(DB):
            sys.exit('索引不存在——先跑全量')
        con = sqlite3.connect(DB, timeout=30)
        if not con.execute("select name from sqlite_master where name='src_state'").fetchone():
            sys.exit('无 src_state——先跑全量或增量')
        prev = dict(con.execute('select path, digest from src_state').fetchall())
        upd, skip, same = [], [], 0
        for p, new in digests.items():
            old = prev.get(p)
            if old is None or old == new:
                same += 1
                continue
            legacy = None
            if p.endswith('/transcript.jsonl'):
                sp = os.path.join(SSOT, p)
                mj = os.path.join(os.path.dirname(sp), 'meta.json')
                legacy = S1VER + ':' + (md5_files(sp, mj) if os.path.isfile(mj) else md5_files(sp))
            if old == legacy:
                upd.append((new, p))
            else:
                skip.append(p)
        con.executemany('update src_state set digest=? where path=?', upd)
        con.commit()
        con.close()
        print(f'✅ restamp：{len(upd)} 源迁到新口径 / {same} 源无变化 / '
              f'{len(skip)} 源内容有变（留给增量）', flush=True)
        for p in skip[:10]:
            print(f'   - 内容有变: {p}', flush=True)
        write_build()
        return
    if '--allow-secret-files' not in sys.argv:
        hits = [path for path, rows in blocks.items()
                if any(SECRET_RX.search((r[1] if len(r) > 1 else '') or '') for r in rows)]
        if hits:
            print(f'❌ 隐私闸：{len(hits)} 源含密钥形态，拒绝索引（先脱敏，或 --allow-secret-files）', flush=True)
            for p in hits[:20]:
                print(f'   - {p}', flush=True)
            sys.exit(2)
    total = sum(len(r) for r in blocks.values())
    print(f'语料：{len(groups)} 源 / {total} 块（文件 {len(fg)} / 会话 {len(sg)} / 子agent {len(sas)}）', flush=True)
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    if not inc:
        con = sqlite3.connect(DB, timeout=30)
        for t in ('chunks_ai', 'chunks_ad', 'chunks_au'):
            con.execute(f'drop trigger if exists {t}')
        con.execute('drop table if exists chunks_fts')
        con.execute('drop table if exists chunks')
        con.execute('create table chunks(id integer primary key, path text, line integer, '
                    'text text, role text, ts text, vec blob)')
        con.execute('drop table if exists src_state')
        con.execute('create table src_state(path text primary key, digest text)')
        n = embed_and_store(con, [g[0] for g in groups], blocks, t0)
        con.executemany('insert or replace into src_state(path,digest) values(?,?)',
                        list(digests.items()))
        ensure_fts(con, rebuild=True)
        con.commit()
        con.close()
        if '--no-pack' in sys.argv:
            print('向量包: 跳过（--no-pack）', flush=True)
        else:
            refresh_pack()
        write_build()
        print(f'✅ 全量 {n} 块 → {DB}  用时 {time.time() - t0:.0f}s')
        if build_dir:
            ready = build_dir[:-len('.building')] if build_dir.endswith('.building') else build_dir
            os.rename(build_dir, ready)
            open(os.path.join(ready, 'STATUS'), 'w', encoding='utf-8').write('ready\n')
            set_active(os.path.basename(ready))
            print('✅ activate：%s（旧版保留，可 --rollback）' % os.path.basename(ready))
        return

    if not os.path.exists(DB):
        sys.exit('索引不存在——先跑全量（无 --incremental）')
    con = sqlite3.connect(DB, timeout=30)
    ensure_fts(con)                 # 已有表则建触发器；缺表则先重建
    db_m = os.path.getmtime(DB)   # 先取样（任何写操作都会顶新 DB mtime）
    if not con.execute("select name from sqlite_master where name='src_state'").fetchone():
        con.execute('create table src_state(path text primary key, digest text)')
        con.commit()
    prev = dict(con.execute('select path, digest from src_state').fetchall())
    # 孤儿清扫（2026-10-15）：清掉任何不在当前语料的历史块
    # （覆盖 bootstrap 前遗留、文件更名/归档后旧路径残留——src_state 里没有的路径也清）
    cur_paths = set(digests)
    db_paths = [r[0] for r in con.execute('select distinct path from chunks').fetchall()]
    orphans = [p for p in db_paths if p not in cur_paths]
    for p in orphans:
        con.execute('delete from chunks where path=?', (p,))
        con.execute('delete from src_state where path=?', (p,))
    if orphans:
        con.commit()
        print(f'孤儿清扫：移除 {len(orphans)} 个历史路径', flush=True)
    if not prev:
        stale = set()
        for g in groups:
            sp = os.path.join(SSOT, g[0])
            if os.path.exists(sp) and os.path.getmtime(sp) > db_m:
                stale.add(g[0])
        print(f'bootstrap：{len(stale)} 源晚于索引，补嵌；其余仅记摘要', flush=True)
        todo = [g[0] for g in groups if g[0] in stale]
        con.executemany('insert or replace into src_state(path,digest) values(?,?)',
                        [(g[0], g[1]) for g in groups if g[0] not in stale])
        con.commit()
    else:
        changed = [g[0] for g in groups if prev.get(g[0]) != g[1]]
        removed = [p for p in prev if p not in digests]
        if not changed and not removed:
            write_build()
            print(f'✅ 增量：无变化（{len(groups)} 源 / {total} 块）  用时 {time.time() - t0:.0f}s')
            return
        old_rows = {}
        if changed:
            q = ','.join('?' * len(changed))
            for path, line, text, role, ts, vec in con.execute(
                    f'select path,line,text,role,ts,vec from chunks where path in ({q})', changed):
                old_rows.setdefault(path, []).append((line, text, role, ts, vec))
        for p in changed + removed:
            con.execute('delete from chunks where path=?', (p,))
        for p in removed:
            con.execute('delete from src_state where path=?', (p,))
        con.commit()
        todo = changed
        print(f'增量：变更 {len(changed)} 源 / 移除 {len(removed)} 源', flush=True)

    if prev:
        n, reused = embed_and_store_diff(con, todo, blocks, old_rows, t0)
    else:
        n, reused = embed_and_store(con, todo, blocks, t0), 0
    con.executemany('insert or replace into src_state(path,digest) values(?,?)',
                    [(p, digests[p]) for p in todo])
    con.commit()
    con.close()
    if '--no-pack' in sys.argv:
        print('向量包: 跳过（--no-pack；语义检索暂时看不到本次新增内容）', flush=True)
    else:
        refresh_pack()
    write_build()
    print(f'✅ 增量完成：新嵌 {n} 块 / 复用 {reused} 块（{len(todo)} 源）  用时 {time.time() - t0:.0f}s')


if __name__ == '__main__' and ('--help' in sys.argv or '-h' in sys.argv):
    print(__doc__)
    raise SystemExit(0)

if __name__ == '__main__':
    sys.exit(main())

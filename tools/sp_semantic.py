#!/usr/bin/env python3
"""sp_semantic · SSOT 语义检索 v7（EmbeddingGemma 2 + numpy 暴力 + 离线考卷）

v2（2026-10-14）：向量 BLOB 直读 + numpy 一次矩阵乘（744 §3 工单 1+2 落地）。
v3（2026-10-14）：对齐 sp_index v3 六列 schema；新增 --role 过滤（user/assistant）。
v4（2026-10-15）：--expand 查询扩展（sp_synonyms.json 别名组 → 多变体，一次矩阵乘融合；+2~3s）。
v5（2026-10-15）：向量包快查——pack-vecs.f32（mmap）+ pack-ids.i64（DB 行号）：载入 2.6~4.5s → 毫秒级；
                  包缺失/过期自动重建（sp_index 跑完也会刷新）；详情按需从 sqlite 取（只取命中的行）。
v6（2026-10-21）：调用留痕 JSONL（caller/sid/query/top1/score）；新增 --eval 离线考卷
                  （Recall@5 / MRR@10 / 负例 precision / 延迟分位；不把评测调用混进采纳日志）。
v7（2026-10-21）：guide 路由 + 符号/意图分叉；canonical 正本内排序（修正扩展候选池截断）；
                  --calibrate 负例/无答案校准；语义扩展默认关闭（消融无净增益，--expand 保留）。
用法：python3 sp_semantic.py "按意思搜的词句" [--top 8] [--path lines] [--role user] [--expand]
      python3 sp_semantic.py --eval knowledge/eval/retrieval-queries.json [--out report.json]
      python3 sp_semantic.py --calibrate knowledge/eval/retrieval-queries-v06.json [--out calib.json]
- 查询前缀固定 `task: search result | query: `（与 sp_index.py 的 doc 前缀配对）
- 索引侧已 L2 归一化 → 本端点积即余弦
需本地 llama-server:8399 在跑（eg2 服务）。
"""
import argparse
import datetime
import json
import math
import os
import re
import sqlite3
import struct
import sys
import time
import urllib.request

import numpy as np

SSOT = os.path.expanduser('~/ssot')
SEM = os.path.join(SSOT, 'S2-index', 'semantic')


def _resolve_db():
    """版本化布局：优先 active.json 指向的版本库；没有就回退 legacy 单库（老目录继续可用）。"""
    try:
        v = json.load(open(os.path.join(SEM, 'active.json'), encoding='utf-8')).get('version')
        p = os.path.join(SEM, 'versions', v, 'index.db')
        if v and os.path.exists(p):
            return p
    except Exception:
        pass
    return os.path.join(SEM, 'index.db')


DB = _resolve_db()
BUILD = os.path.join(os.path.dirname(DB), 'BUILD.json')
API = 'http://127.0.0.1:8399/v1/embeddings'
QUERY_PREFIX = 'task: search result | query: '
SYN_FILE = os.path.join(SSOT, 'tools', 'sp_synonyms.json')
LOG = os.path.join(SSOT, 'S2-index', 'search-log.jsonl')
KEY_RX = re.compile(r'(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,}|hf_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})')
NEG_THRESHOLD = 0.62
EXPAND_VARIANT_WEIGHT = 0.9    # 变体只补召回，不让改写句反客为主（1.0=等权 max，实测会稀释）
AUTO_SEMANTIC_EXPAND = False    # 调参集消融：开启无净增益、p50 +350ms；留 --expand 手动开关


def log_call(tool, query, n, top1, ms, status='ok', extra=None):
    """调用留痕（本地 JSONL；查询脱敏截断；日志失败绝不影响检索）。"""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rec = {
            'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'tool': tool,
            'caller': os.environ.get('SSOT_CALLER', 'cli'),
            'sid': (os.environ.get('SSOT_SESSION_ID') or os.environ.get('QODER_SESSION_ID')
                    or os.environ.get('CLAUDE_SESSION_ID') or '-'),
            'query': KEY_RX.sub('[redacted]', ' '.join(query.split()))[:200],
            'n': n,
            'ms': int(ms),
            'status': status,
        }
        if top1:
            rec.update({'top1_path': top1[0], 'top1_line': top1[1],
                        'top1_score': round(float(top1[2]), 4)})
        if extra:
            rec.update(extra)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        os.chmod(LOG, 0o600)
    except Exception:
        pass


def build_commit():
    try:
        with open(BUILD, encoding='utf-8') as f:
            return json.load(f).get('commit') or '-'
    except Exception:
        return '-'


def load_synonym_groups():
    try:
        with open(SYN_FILE, encoding='utf-8') as f:
            return json.load(f).get('groups', [])
    except Exception:
        return []


def _term_rx(term):
    if any(c.isascii() for c in term):
        return re.compile(r'(?i)(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])')
    return re.compile(re.escape(term))


def expand_queries(query, groups, cap=3):
    """→ [(变体文本, 标签)]；别名组命中词替换为同组他词；最多 cap 个变体。"""
    out, seen = [], {query}
    for g in groups:
        hit = m = None
        for t in g:
            m2 = _term_rx(t).search(query)
            if m2:
                hit, m = t, m2
                break
        if not hit:
            continue
        for alias in g:
            if alias == hit:
                continue
            v = query[:m.start()] + alias + query[m.end():]
            if v not in seen:
                seen.add(v)
                out.append((v, f'{hit}→{alias}'))
            if len(out) >= cap:
                return out
    return out


PACK_VECS = os.path.join(os.path.dirname(DB), 'pack-vecs.f32')
PACK_IDS = os.path.join(os.path.dirname(DB), 'pack-ids.i64')


def pack_fresh(db=DB):
    try:
        return (os.path.exists(PACK_VECS) and os.path.exists(PACK_IDS)
                and os.path.getmtime(PACK_VECS) >= os.path.getmtime(db))
    except OSError:
        return False


def build_pack(db=DB, quiet=False, pack_vecs=PACK_VECS, pack_ids=PACK_IDS):
    """把 chunks 的向量抽成 mmap 友好的 pack-vecs.f32 + pack-ids.i64。返回 (行数, 秒)。"""
    if not os.path.exists(db):
        return (0, 0.0)
    t0 = time.time()
    con = sqlite3.connect(db)
    tv, ti = pack_vecs + '.tmp', pack_ids + '.tmp'
    n = 0
    last_report = 0
    with open(tv, 'wb') as fv, open(ti, 'wb') as fi:
        for rid, vec in con.execute('select id, vec from chunks order by id'):
            fv.write(vec)
            fi.write(struct.pack('<q', rid))
            n += 1
            if not quiet and n - last_report >= 50000:
                print(f'向量包: {n} 行 {time.time() - t0:.0f}s', flush=True)
                last_report = n
    con.close()
    os.replace(tv, pack_vecs)
    os.replace(ti, pack_ids)
    secs = time.time() - t0
    if not quiet:
        print(f'向量包: 重建 {n} 行（{secs:.0f}s）→ {pack_vecs}', flush=True)
    return (n, secs)


def build_pack_incremental(db=DB, quiet=False, pack_vecs=PACK_VECS, pack_ids=PACK_IDS,
                           max_stale=2000, max_missing=5000):
    """增量追加 pack；stale/缺失过多时回退全量重建（压实）。

    设计：pack 允许保留已删除行的旧向量（搜索取详情时会跳过），
    但 stale 超过 max_stale 或一次缺太多时，做一次全量压实。
    返回 dict：mode=noop|append|rebuild, n, appended, stale, secs。
    """
    t0 = time.time()
    if not (os.path.exists(db) and os.path.exists(pack_vecs) and os.path.exists(pack_ids)):
        n, secs = build_pack(db, quiet=quiet, pack_vecs=pack_vecs, pack_ids=pack_ids)
        return {'mode': 'rebuild', 'n': n, 'appended': 0, 'stale': 0, 'secs': secs}
    ids = np.fromfile(pack_ids, dtype=np.int64)
    if not len(ids):
        n, secs = build_pack(db, quiet=quiet, pack_vecs=pack_vecs, pack_ids=pack_ids)
        return {'mode': 'rebuild', 'n': n, 'appended': 0, 'stale': 0, 'secs': secs}
    con = sqlite3.connect(db)
    dbids = np.fromiter((r[0] for r in con.execute('select id from chunks order by id')),
                        dtype=np.int64)
    missing = np.setdiff1d(dbids, ids, assume_unique=False)
    stale = np.setdiff1d(ids, dbids, assume_unique=False)
    if len(missing) == 0 and len(stale) <= max_stale:
        con.close()
        return {'mode': 'noop', 'n': len(ids), 'appended': 0,
                'stale': int(len(stale)), 'secs': time.time() - t0}
    if len(missing) > max_missing or len(stale) > max_stale:
        con.close()
        n, secs = build_pack(db, quiet=quiet, pack_vecs=pack_vecs, pack_ids=pack_ids)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
    total = os.path.getsize(pack_vecs) // 4
    if total % len(ids):
        con.close()
        n, secs = build_pack(db, quiet=quiet, pack_vecs=pack_vecs, pack_ids=pack_ids)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
    dim = total // len(ids)
    q = ','.join('?' * len(missing))
    rows = con.execute(f'select id, vec from chunks where id in ({q}) order by id',
                       [int(x) for x in missing]).fetchall()
    con.close()
    if len(rows) != len(missing) or any(len(v) // 4 != dim for _rid, v in rows):
        n, secs = build_pack(db, quiet=quiet, pack_vecs=pack_vecs, pack_ids=pack_ids)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
    import shutil
    tv, ti = pack_vecs + '.tmp', pack_ids + '.tmp'
    shutil.copyfile(pack_vecs, tv)
    shutil.copyfile(pack_ids, ti)
    with open(tv, 'ab') as fv, open(ti, 'ab') as fi:
        for rid, vec in rows:
            fv.write(vec)
            fi.write(struct.pack('<q', int(rid)))
        os.fsync(fv.fileno())
        os.fsync(fi.fileno())
    os.replace(tv, pack_vecs)
    os.replace(ti, pack_ids)
    secs = time.time() - t0
    if not quiet:
        print(f'向量包: 增量追加 {len(rows)} 行（stale {len(stale)}，{secs:.0f}s）', flush=True)
    return {'mode': 'append', 'n': len(ids) + len(rows), 'appended': len(rows),
            'stale': int(len(stale)), 'secs': secs}


_PACK_OVERRIDE = None


def load_pack():
    """→ (memmap(N,dim), int64[N])；不可用时 (None, None)。
    _PACK_OVERRIDE 由常驻 daemon 注入(整包读进匿名内存,避免页被回收后重新触页)。"""
    if _PACK_OVERRIDE is not None:
        return _PACK_OVERRIDE
    try:
        ids = np.fromfile(PACK_IDS, dtype=np.int64)
        total = os.path.getsize(PACK_VECS) // 4
        if not len(ids) or total % len(ids):
            return (None, None)
        M = np.memmap(PACK_VECS, dtype=np.float32, mode='r').reshape(len(ids), total // len(ids))
        return (M, ids)
    except Exception:
        return (None, None)


def fetch_rows(ids_list, db=DB):
    """按 DB 行号取详情（只取命中的几行）。"""
    out = {}
    if not ids_list:
        return out
    con = sqlite3.connect(db)
    q = ','.join('?' * len(ids_list))
    for rid, path, line, text, role, ts in con.execute(
            f'select id, path, line, text, role, ts from chunks where id in ({q})', ids_list):
        out[rid] = (path, line, text, role, ts)
    con.close()
    return out


def embed(text):
    req = urllib.request.Request(
        API,
        data=json.dumps({'input': [text]}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())['data'][0]['embedding']


CANON_PREFIXES = ('knowledge/', 'lines/', 'inbox/', 'profile/')
SYMBOL_RX = re.compile(
    r'(?<![\w-])(?:A\d{3,}|[A-Za-z]+[-_][A-Za-z0-9_-]+|[A-Za-z]+\d+(?:[-_]\d+[A-Za-z]*)?|'
    r'\d+\s*[组个条]|\d{3,}|\d+\.\d+|[A-Z]{2,}|[A-Z][a-z]+(?:[A-Z][a-z]+)+)(?![\w-])')
TEMPORAL_RX = re.compile(r'现在|最近|停在|推进到|什么阶段|在做什么|哪个批次|到哪了')
ONBOARD_RX = re.compile(r'开工|新会话|读档|先读|接手')
GUIDE_RX = re.compile(r'操作正本|正本在哪|操作指南|GUIDE')
EXACT_ID_RX = re.compile(
    r'(?<![\w-])A\d{3,}|(?<![\w-])\d{3,}(?![\w-])|[A-Za-z]+[-_][A-Za-z0-9_-]+|'
    r'[A-Za-z]+\d+(?:[-_]\d+[A-Za-z]*)?|[A-Z][a-z]+(?:[A-Z][a-z]+)+')
INTENT_RX = re.compile(r'怎么|如何|为什么|为啥|防止|处理|恢复|原理|区别|分几层|在哪')


def route_query(query):
    if ONBOARD_RX.search(query):
        return 'onboard'
    if GUIDE_RX.search(query):
        return 'guide'
    if TEMPORAL_RX.search(query):
        return 'lines' if ('线' in query or '批次' in query or '阶段' in query or '推进' in query) else 'canonical'
    if SYMBOL_RX.search(query):
        if INTENT_RX.search(query) and not EXACT_ID_RX.search(query):
            return 'semantic'
        return 'symbol'
    return 'semantic'


_CANON_CACHE = {'mtime': None, 'map': {}}


def canon_paths():
    """canonical chunk id → path（按 DB mtime 缓存；正本约 1.5k 行）。"""
    try:
        mt = os.path.getmtime(DB)
    except OSError:
        return {}
    if _CANON_CACHE['mtime'] != mt:
        con = sqlite3.connect(DB, timeout=15)
        rows = con.execute(
            "select id,path from chunks where path in ('START.md','GUIDE.md') "
            "or path like 'knowledge/%' or path like 'lines/%' or path like 'inbox/%' "
            "or path like 'profile/%'").fetchall()
        con.close()
        _CANON_CACHE.update(mtime=mt, map=dict(rows))
    return _CANON_CACHE['map']


def exact_candidates(query, limit=200):
    """精确标识（A381/8399/BPE/lfc_publish/8 组…）在正本层的 LIKE 候选。"""
    syms = []
    for m in SYMBOL_RX.finditer(query):
        s = ' '.join(m.group(0).split())
        if s and s not in syms:
            syms.append(s)
    if not syms:
        return []
    con = sqlite3.connect(DB, timeout=15)
    rows = []
    try:
        for sym in syms[:4]:
            rows += con.execute(
                "select c.id,c.path,c.line from chunks_fts f join chunks c on c.id=f.rowid "
                "where f.chunks_fts match ? and (c.path='START.md' or c.path like 'knowledge/%' "
                "or c.path like 'lines/%' or c.path like 'inbox/%' or c.path like 'profile/%') "
                "order by case when c.path='START.md' or c.path like 'knowledge/%' or c.path like 'lines/%' "
                "then 0 when c.path like 'inbox/%' then 1 when c.path like 'profile/%' then 2 else 3 end, "
                "c.path, c.line limit ?",
                (f'"{sym}"', limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()
    seen = {}
    for rid, path, _line in rows:
        c, p = seen.get(rid, (0, path))
        seen[rid] = (c + 1, p)

    def prio(path):
        if path == 'START.md' or path.startswith(('knowledge/', 'lines/')):
            return 0
        if path.startswith('inbox/'):
            return 1
        if path.startswith('profile/'):
            return 2
        return 3

    ordered = sorted(seen.items(), key=lambda kv: (-kv[1][0], prio(kv[1][1]), kv[0]))
    return [(1.0 / (i + 1), rid) for i, (rid, _v) in enumerate(ordered)]


def _fts_terms(q):
    """查询 → FTS5 trigram 词项（ASCII 词 + 中文 3-gram）。"""
    q = re.sub(r'[^\w\u4e00-\u9fff]+', ' ', q)
    terms = []
    for tok in q.split():
        if any('\u4e00' <= c <= '\u9fff' for c in tok):
            if len(tok) < 3:
                continue
            terms.extend(tok[i:i + 3] for i in range(len(tok) - 2))
        elif len(tok) >= 3:
            terms.append(tok)
    out = []
    for t in terms:
        if t not in out:
            out.append(t)
    return out[:24]


def bm25_search(query, limit=300):
    """FTS5 trigram BM25 → [(score, rowid)]（score 已转正）。"""
    terms = _fts_terms(query)
    if not terms:
        return []
    match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
    con = sqlite3.connect(DB, timeout=15)
    try:
        rows = con.execute(
            'select rowid, bm25(chunks_fts) as s from chunks_fts '
            'where chunks_fts match ? order by s limit ?', (match, limit)).fetchall()
    except sqlite3.OperationalError as e:
        raise RuntimeError(f'no_fts: {e}')
    finally:
        con.close()
    return [(-float(s), int(rid)) for rid, s in rows]


def _rrf(orders, weights, k=60):
    fused = {}
    for order, w in zip(orders, weights):
        for rank, (_s, rid) in enumerate(order, 1):
            fused[rid] = fused.get(rid, 0.0) + w / (k + rank)
    return [(float(score), int(rid)) for rid, score in sorted(fused.items(), key=lambda x: -x[1])]


def run_search(query, top=8, path=None, role=None, expand=False, mode='dense'):
    """执行一次检索 → (results, meta)。results 为按分数降序的 dict 列表。"""
    requested_mode = mode
    route = None
    if mode == 'route':
        # 2026-11-01 实测:技术短查询 hybrid2 反而差(dense 0.78 vs 0.087)
        tech = bool(re.search(r'[A-Za-z][A-Za-z0-9_./:#-]{2,}|\d{2,}', query)) and len(query) <= 64
        route = 'tech' if tech else 'prose'
        mode = 'dense' if tech else 'hybrid2'
    if mode == 'route3':
        # 2026-11-01 三轮路由实测:状态问句→lines;长引文→dense;其余→hybrid2
        if re.search(r'(线现在在做什么|线最近有什么进展|最近有什么进展|现在在做什么)', query):
            route = 'line-status'; mode = 'lines'
        elif len(query) >= 50:
            route = 'long-quote'; mode = 'dense'
        else:
            route = 'default'; mode = 'hybrid2'
    if mode == 'route2':
        # 2026-11-01:60 题里 17 个失败全是"<线> 线现在在做什么/最近有什么进展" → 走 lines
        if re.search(r'(线现在在做什么|线最近有什么进展|最近有什么进展|现在在做什么)', query):
            route = 'line-status'; mode = 'lines'
        else:
            route = 'default'; mode = 'hybrid2'
    if mode == 'auto':
        route = route_query(query)
        if route == 'semantic' and AUTO_SEMANTIC_EXPAND:
            expand = True          # exact/temporal/onboard 永不扩展；semantic 默认关闭（见消融）
        mode = 'canonical' if route == 'semantic' else ('canonical_hybrid' if route == 'symbol' else route)
    t0 = time.time()
    if not os.path.exists(DB):
        raise RuntimeError('no_index')
    variants = expand_queries(query, load_synonym_groups()) if expand else []
    qtexts = [query] + [v for v, _ in variants]
    try:
        Q = np.array([np.asarray(embed(QUERY_PREFIX + qt), dtype=np.float32) for qt in qtexts])
    except Exception as e:
        raise RuntimeError(f'embed_error: {e}')
    Q /= (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-9)
    t_enc = time.time() - t0
    if not pack_fresh():
        print('（向量包缺失/过期——重建中，仅此一次…）', file=sys.stderr, flush=True)
        try:
            build_pack_incremental(quiet=True)
        except Exception:
            build_pack(quiet=True)
    M, ids = load_pack()
    if ids is None:                     # 兜底：整流载入（老路径）
        con = sqlite3.connect(DB, timeout=15)
        rows = con.execute('select id, vec from chunks order by id').fetchall()
        con.close()
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        M = np.frombuffer(b''.join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    N = len(ids)
    t_load = time.time() - t0 - t_enc
    sims_all = M @ Q.T                  # (N, k) 一次矩阵乘出全部变体分
    t_calc = time.time() - t0 - t_enc - t_load
    if len(qtexts) == 1:
        col = sims_all[:, 0]
        order = [(float(col[i]), int(ids[i])) for i in np.argsort(-col)]
    else:
        canon_modes = ('canonical', 'lines', 'onboard', 'guide', 'canonical_hybrid')
        pool = N if (path or role or mode in canon_modes) else max(top * 8, 64)
        best = {}
        for vi in range(len(qtexts)):
            col = sims_all[:, vi]
            for i in np.argsort(-col)[:pool]:
                rid = int(ids[i])
                s = float(col[i]) * (1.0 if vi == 0 else EXPAND_VARIANT_WEIGHT)
                if rid not in best or s > best[rid]:
                    best[rid] = s
        order = sorted(((s, r) for r, s in best.items()), key=lambda x: -x[0])

    if mode in ('hybrid', 'hybrid2', 'hybrid2d', 'canonical_hybrid'):
        dense_all = order
        bm = bm25_search(query, limit=300)
        exact = exact_candidates(query) if SYMBOL_RX.search(query) else []
        if mode == 'canonical_hybrid':
            cp = canon_paths()
            dense_c = [(s, rid) for s, rid in dense_all if rid in cp]
            bm_c = [(s, rid) for s, rid in bm if rid in cp]
            order = _rrf([dense_c[:300], bm_c[:300], exact], [1.0, 1.0, 3.0])
            if len(order) < top:      # 正本不足才回证据层
                full = _rrf([dense_all[:300], bm[:300], exact], [1.0, 1.0, 3.0])
                seen = {rid for _s, rid in order}
                order += [(s, rid) for s, rid in full if rid not in seen]
        elif mode == 'hybrid':
            order = _rrf([order[:300], bm, exact], [1.0, 1.0, 3.0])
        else:
            cp = canon_paths()

            def is_canon(rid):
                return rid in cp

            fused = {}
            for rank, (_s, rid) in enumerate(order[:800], 1):
                fused[rid] = fused.get(rid, 0.0) + (2.0 if is_canon(rid) else 1.0) / (60 + rank)
            for rank, (_s, rid) in enumerate(bm, 1):
                fused[rid] = fused.get(rid, 0.0) + (2.0 if is_canon(rid) else 1.0) / (60 + rank)
            for rank, (_s, rid) in enumerate(exact, 1):
                fused[rid] = fused.get(rid, 0.0) + 3.0 / (60 + rank)
            order = [(float(score), int(rid)) for rid, score in sorted(fused.items(), key=lambda x: -x[1])]
            if mode == 'hybrid2d':          # 与纯 dense 再融合一次(2026-11-01 试)
                order = _rrf([dense_all[:300], order[:300]], [1.0, 1.0])
    elif mode in ('canonical', 'lines', 'onboard', 'guide'):
        cp = canon_paths()
        if mode == 'onboard':
            kept = [(s, rid) for s, rid in order
                    if cp.get(rid) == 'START.md' or (cp.get(rid) or '').startswith('profile/')]
        elif mode == 'lines':
            kept = [(s, rid) for s, rid in order if (cp.get(rid) or '').startswith('lines/')]
        elif mode == 'guide':
            kept = [(s, rid) for s, rid in order if cp.get(rid) in ('GUIDE.md', 'START.md')]
        else:
            kept = [(s, rid) for s, rid in order if rid in cp]
        if len(kept) < top:        # 线页/入口不够时用其余正本兜底
            seen = {rid for _s, rid in kept}
            kept += [(s, rid) for s, rid in order if rid in cp and rid not in seen]
        order = kept

    detail, pos, shown = {}, 0, 0
    results = []
    while shown < top and pos < len(order):
        window = order[pos:pos + 256]
        pos += 256
        miss = [rid for _s, rid in window if rid not in detail]
        if miss:
            detail.update(fetch_rows(miss))
        for s, rid in window:
            d = detail.get(rid)
            if not d:
                continue
            p, line, text, r, _ts = d
            if path and path not in p:
                continue
            if role and r != role:
                continue
            results.append({'score': float(s), 'path': p, 'line': line,
                            'text': text or '', 'role': r})
            shown += 1
            if shown >= top:
                break
    meta = {'N': N, 'ms': (time.time() - t0) * 1000,
            't_enc': t_enc * 1000, 't_load': t_load * 1000, 't_calc': t_calc * 1000,
            'variants': variants,
            'mode': (requested_mode if requested_mode != 'auto' else 'auto:' + (route or mode))}
    return results, meta



def run_search_by_vec(vec, top=8, path=None, role=None):
    """用**预置查询向量**检索(跳过编码,供 daemon 拆"检索段"口径)。
    与 dense 路径打分逻辑一致;仅省掉编码。"""
    t0 = time.time()
    if not os.path.exists(DB):
        raise RuntimeError('no_index')
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v)) + 1e-9
    v = v / n
    M, ids = load_pack()
    if M is None:
        raise RuntimeError('no_index')
    N = len(ids)
    t_load = time.time() - t0
    t_c = time.time()
    col = M @ v
    order = [(float(col[i]), int(ids[i])) for i in np.argsort(-col)]
    t_calc = time.time() - t_c
    detail, pos, shown = {}, 0, 0
    results = []
    while shown < top and pos < len(order):
        window = order[pos:pos + 256]
        pos += 256
        miss = [rid for _s, rid in window if rid not in detail]
        if miss:
            detail.update(fetch_rows(miss))
        for sc, rid in window:
            d = detail.get(rid)
            if not d:
                continue
            p, line, text, r, _ts = d
            if path and path not in p:
                continue
            if role and r != role:
                continue
            results.append({'score': float(sc), 'path': p, 'line': line, 'text': text or '', 'role': r})
            shown += 1
            if shown >= top:
                break
    meta = {'N': N, 'ms': (time.time() - t0) * 1000, 't_enc': 0.0,
            't_load': t_load * 1000, 't_calc': t_calc * 1000, 'variants': [], 'mode': 'dense:vec'}
    return results, meta

def _path_match(p, exps):
    p = (p or '').replace('\\', '/')
    for e in exps or []:
        e = e.replace('\\', '/').lstrip('./')
        if p == e or p.endswith('/' + e) or p.startswith(e.rstrip('/') + '/'):
            return True
    return False


def _fact_match(text, must):
    t = (text or '').lower()
    return all(str(m).lower() in t for m in (must or []))


def _pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round((len(s) - 1) * q)))]


def run_eval(path, top=10, expand=False, out=None, mode='dense'):
    """固定考卷：Recall@5 / MRR@10 / 负例 precision / 延迟分位。"""
    with open(path, encoding='utf-8') as f:
        qs = json.load(f)
    calibrated = (mode == 'dense')
    rows, lat = [], []
    for q in qs:
        res, meta = run_search(q['query'], top=top,
                               expand=expand or bool(q.get('expand', False)), mode=mode)
        lat.append(meta['ms'])
        top1 = res[0] if res else None
        if q.get('negative'):
            score = top1['score'] if top1 else 0.0
            rows.append({'id': q.get('id'), 'type': q.get('type', 'negative'),
                         'query': q['query'], 'negative': True,
                         'ok': (score < NEG_THRESHOLD) if calibrated else None,
                         'top1_score': round(score, 4),
                         'top1_path': top1['path'] if top1 else None})
            continue
        rank = None
        for i, r in enumerate(res[:top], 1):
            if _path_match(r['path'], q.get('expected_paths')) and _fact_match(r.get('text'), q.get('must_have')):
                rank = i
                break
        rows.append({'id': q.get('id'), 'type': q.get('type', 'semantic'),
                     'query': q['query'], 'negative': False,
                     'rank': rank, 'recall5': bool(rank and rank <= 5),
                     'rr': (1.0 / rank if rank else 0.0),
                     'top1_path': top1['path'] if top1 else None,
                     'top1_score': round(top1['score'], 4) if top1 else None,
                     'expected_paths': q.get('expected_paths', [])})

    pos = [r for r in rows if not r['negative']]
    neg = [r for r in rows if r['negative']]

    def agg(rs):
        rs = [r for r in rs if not r.get('negative')]
        return {'n': len(rs),
                'recall@5': round(sum(r['recall5'] for r in rs) / len(rs), 3) if rs else None,
                'mrr@10': round(sum(r['rr'] for r in rs) / len(rs), 3) if rs else None}

    by_type = {}
    for t in sorted(set(r['type'] for r in rows)):
        by_type[t] = agg([r for r in rows if r['type'] == t])
    neg_scores = [r['top1_score'] for r in neg]
    if neg:
        by_type['negative'] = {'n': len(neg),
                               'top1_max': max(neg_scores),
                               'top1_mean': round(sum(neg_scores) / len(neg_scores), 3)}
        if calibrated:
            by_type['negative']['negative_precision'] = round(sum(r['ok'] for r in neg) / len(neg), 3)
    report = {
        'queries': path, 'n': len(rows), 'top': top, 'expand': bool(expand), 'mode': mode,
        'recall@5': agg(pos)['recall@5'],
        'mrr@10': agg(pos)['mrr@10'],
        'negative_calibrated': calibrated,
        'negative_precision': round(sum(r['ok'] for r in neg) / len(neg), 3) if (neg and calibrated) else None,
        'negative_threshold': NEG_THRESHOLD if calibrated else None,
        'negative_top1_max': max(neg_scores) if neg_scores else None,
        'negative_top1_mean': round(sum(neg_scores) / len(neg_scores), 3) if neg_scores else None,
        'latency_ms': {'p50': round(_pct(lat, 0.5), 1), 'p95': round(_pct(lat, 0.95), 1)},
        'by_type': by_type,
        'failures': [r for r in rows
                     if (r['negative'] and r.get('ok') is False)
                     or (not r['negative'] and not r['recall5'])],
        'rows': rows,
    }
    js = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(js + '\n')
    print(js)


def _stats(vals):
    if not vals:
        return None
    s = sorted(vals)
    return {'n': len(s), 'min': round(s[0], 4), 'p10': round(_pct(s, 0.1), 4),
            'p50': round(_pct(s, 0.5), 4), 'p90': round(_pct(s, 0.9), 4),
            'max': round(s[-1], 4), 'mean': round(sum(s) / len(s), 4)}


def _auc(pos, neg):
    """P(正例分数 > 负例分数) + 0.5*持平；0.5=无区分力。"""
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return round(wins / (len(pos) * len(neg)), 3)


def _sweep(pos, neg):
    """阈值 t：top1 < t 判「无答案」。返回 best-F1 与高精度保守点。"""
    vals = sorted(set(pos + neg))
    if not vals:
        return None
    cands = [vals[0] - 1e-6] + [(a + b) / 2 for a, b in zip(vals, vals[1:])] + [vals[-1] + 1e-6]
    best = None
    for t in cands:
        tp = sum(1 for s in neg if s < t)
        fp = sum(1 for s in pos if s < t)
        fn = len(neg) - tp
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / len(neg) if neg else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        row = {'threshold': round(t, 4), 'precision': round(p, 3),
               'recall': round(r, 3), 'f1': round(f1, 3)}
        if best is None or f1 > best['f1'] or (f1 == best['f1'] and p > best['precision']):
            best = row
    return {'best_f1': best, 'auc': _auc(pos, neg)}


def run_calibrate(path, out=None):
    """负例/无答案校准：dense / BM25 / auto 三通道分数分布 + 阈值扫描。"""
    with open(path, encoding='utf-8') as f:
        qs = json.load(f)
    rows = []
    for q in qs:
        query = q['query']
        route = route_query(query)
        dres, _ = run_search(query, top=1, expand=False, mode='dense')
        ares, _ = run_search(query, top=1, expand=False, mode='auto')
        bm = bm25_search(query, limit=1)
        rows.append({'id': q.get('id'), 'query': query, 'negative': bool(q.get('negative')),
                     'type': q.get('type', 'negative' if q.get('negative') else 'semantic'),
                     'route': route,
                     'dense': round(dres[0]['score'], 4) if dres else 0.0,
                     'bm25': round(bm[0][0], 4) if bm else 0.0,
                     'auto': round(ares[0]['score'], 4) if ares else 0.0})
    pos = [r for r in rows if not r['negative']]
    neg = [r for r in rows if r['negative']]
    auto_pos = [r for r in pos if r['route'] == 'semantic']
    auto_neg = [r for r in neg if r['route'] == 'semantic']
    report = {
        'queries': path, 'n': len(rows), 'n_pos': len(pos), 'n_neg': len(neg),
        'method': 'top1 < threshold → no-answer；dense=全局向量 top1；BM25=FTS5 trigram top1；'
                  'auto=路由后 top1（仅 semantic 路由可比，temporal/exact 的 RRF 分数量纲不同）',
        'channels': {
            'dense': {'pos': _stats([r['dense'] for r in pos]),
                      'neg': _stats([r['dense'] for r in neg]),
                      'sweep': _sweep([r['dense'] for r in pos], [r['dense'] for r in neg])},
            'bm25': {'pos': _stats([r['bm25'] for r in pos]),
                     'neg': _stats([r['bm25'] for r in neg]),
                     'sweep': _sweep([r['bm25'] for r in pos], [r['bm25'] for r in neg])},
            'auto_semantic': {'pos': _stats([r['auto'] for r in auto_pos]),
                              'neg': _stats([r['auto'] for r in auto_neg]),
                              'sweep': _sweep([r['auto'] for r in auto_pos], [r['auto'] for r in auto_neg])},
        },
        'rows': rows,
    }
    js = json.dumps(report, ensure_ascii=False, indent=2)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(js + '\n')
    print(js)



SOCK_PATH = os.path.expanduser('~/.ssot/semantic.sock')


def daemon_search(query, top=8, path=None, role=None, expand=False, mode='dense', timeout=5.0):
    """走常驻 daemon;任何异常由调用方降级到一次性路径(A5)"""
    import json as _json
    import socket as _socket
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK_PATH)
        req = {'query': query, 'top': top, 'path': path, 'role': role,
               'expand': bool(expand), 'mode': mode}
        s.sendall((_json.dumps(req, ensure_ascii=False) + '\n').encode())
        buf = b''
        while b'\n' not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    if not buf:
        raise RuntimeError('daemon_empty')
    resp = _json.loads(buf.split(b'\n', 1)[0].decode('utf-8'))
    if not resp.get('ok'):
        raise RuntimeError(resp.get('error') or 'daemon_error')
    return resp['results'], resp['meta']

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_contract import guard as _contract_guard
    if not _contract_guard('sp_semantic', write=False):
        return 2
    ap = argparse.ArgumentParser(
    epilog='【契约】意图：按意思检索全库；不改数据\n退出码：0=有结果；非0=无索引/嵌入服务不可用\n失败后：起 :8399 或 sp_index --incremental；临时 --oneshot\n\n示例:\n  sp_semantic.py "<问题>" --expand --top 5\n  sp_semantic.py "<问题>" --path lines/ --role user --top 5\n前提:pack 与 BUILD.json 已就绪;chunks=0 或 pack 缺失会直接报错(先跑 sp_index)。',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('query', nargs='?', default=None)
    ap.add_argument('--top', type=int, default=8)
    ap.add_argument('--path', default=None, help='路径子串过滤，如 lines / S1-sessions')
    ap.add_argument('--role', default=None, help='角色过滤：user / assistant（S1 块）')
    ap.add_argument('--expand', action='store_true',
                    help='查询扩展：按 sp_synonyms.json 别名组多变体融合（+2~3s）')
    ap.add_argument('--mode', choices=('dense', 'hybrid', 'hybrid2', 'canonical_hybrid', 'canonical', 'lines', 'onboard', 'guide', 'auto', 'route', 'route2', 'route3', 'hybrid2d'),
                    default='dense',
                    help='dense=纯向量；hybrid=BM25+RRF；hybrid2=正本加权+符号；canonical_hybrid=正本优先两阶段；canonical=只查正本；lines=线页优先；onboard=START/profile 优先；guide=GUIDE/START 优先；auto=按查询路由')
    ap.add_argument('--eval', default=None, help='离线考卷 JSON 路径')
    ap.add_argument('--calibrate', default=None, metavar='FILE',
                    help='负例/无答案校准：dense/BM25/auto 分数分布 + 阈值扫描')
    ap.add_argument('--out', default=None, help='--eval/--calibrate 的 JSON 报告输出路径')
    ap.add_argument('--oneshot', action='store_true', help='强制走一次性进程(绕过 daemon)')
    a = ap.parse_args()

    if a.calibrate:
        try:
            run_calibrate(a.calibrate, out=a.out)
        except RuntimeError as e:
            sys.exit(f'校准失败：{e}（先跑 python3 tools/sp_index.py --fts-only）')
        return

    if a.eval:
        try:
            run_eval(a.eval, top=max(a.top, 10), expand=a.expand, out=a.out, mode=a.mode)
        except RuntimeError as e:
            sys.exit(f'评测失败：{e}（先跑 python3 tools/sp_index.py --fts-only）')
        return

    if not a.query:
        sys.exit(__doc__)
    t0 = time.time()
    results = meta = None
    if (not a.oneshot) and os.environ.get('SSOT_SEMANTIC_ONESHOT') != '1' and os.path.exists(SOCK_PATH):
        try:
            results, meta = daemon_search(a.query, top=a.top, path=a.path, role=a.role,
                                          expand=a.expand, mode=a.mode)
        except Exception as _e:  # noqa: BLE001 —— 降级是硬要求(A5)
            log_call('sp_semantic', a.query, 0, None, (time.time() - t0) * 1000,
                     status='daemon_fallback', extra={'error': str(_e)[:120]})
    try:
        if results is None:
            results, meta = run_search(a.query, top=a.top, path=a.path, role=a.role,
                                       expand=a.expand, mode=a.mode)
    except RuntimeError as e:
        msg = str(e)
        if msg == 'no_index':
            status = 'no_index'
        elif msg.startswith('embed_error'):
            status = 'embed_error'
        elif msg.startswith('no_fts'):
            status = 'no_fts'
        else:
            status = 'error'
        log_call('sp_semantic', a.query, 0, None, (time.time() - t0) * 1000,
                 status=status, extra={'error': msg[:200]})
        if msg == 'no_index':
            sys.exit('索引不存在——先跑 sp_index.py')
        if msg.startswith('embed_error'):
            sys.exit(f'嵌入服务错误：{msg}')
        if msg.startswith('no_fts'):
            sys.exit('FTS 索引缺失——先跑 python3 tools/sp_index.py --fts-only')
        sys.exit(f'检索失败：{msg}')

    variants = meta['variants']
    ext = (f' · 扩展 {len(variants)} 变体（' + '｜'.join(t for _v, t in variants) + '）') if variants else ''
    print(f"query: {a.query}  （库 {meta['N']} 块 · commit {build_commit()} · 编码 {meta['t_enc']:.0f}ms + 载入 {meta['t_load']:.0f}ms + 检索 {meta['t_calc']:.0f}ms{ext}）\n")
    for r in results:
        rr = f" · {r['role']}" if r['role'] else ''
        snippet = ' '.join((r['text'] or '').split())[:110]
        print(f"[{r['score']:.3f}] {r['path']}:{r['line']}{rr}")
        print(f'        {snippet}')
    top1 = (results[0]['path'], results[0]['line'], results[0]['score']) if results else None
    log_call('sp_semantic', a.query, len(results), top1, (time.time() - t0) * 1000,
             extra={'k': a.top, 'expand': bool(variants), 'path': a.path, 'role': a.role})


if __name__ == '__main__':
    sys.exit(main())

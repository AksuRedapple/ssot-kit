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
--status      只读：active/库/版本/config（batch 来自 profile 或 SP_INDEX_BATCH）
--plan        只读：按 profile/index-policy.json 列出 include/skip 与理由
--apply-policy 删除 policy 跳过源的块+src_state（显式；也可由 --incremental 孤儿清扫完成）
--all-classes 忽略 session_class 过滤；--class c1,c2 只索引指定类；--include-retired 包含已退休源
配置: client.batch 优先级 SP_INDEX_BATCH > profile/embed-profile.json > 32；workers 默认 1（并发未启用）
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import policy as sp_policy  # noqa: E402
from ssotlib import fingerprint as sp_fingerprint  # noqa: E402
from ssotlib import asserts as sp_assert_lib  # noqa: E402
from ssotlib import pending as sp_pending  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
from ssotlib.index import embed as _embed  # noqa: E402
from ssotlib.index import layout as _layout  # noqa: E402
from ssotlib.index import pack as _pack  # noqa: E402
from ssotlib.index.chunking import chunk_file  # noqa: E402

SEM = _layout.SEM
PROFILE = os.path.expanduser(os.environ.get(
    'EMBED_PROFILE', os.path.join(SSOT, 'profile', 'embed-profile.json')))
DB = _layout.LEGACY_DB                      # legacy（v1 单库）；版本化后仅作兜底
VERS = _layout.VERS                         # 每个全量构建一个版本目录
ACTIVE = _layout.ACTIVE                     # 唯一在线指针（原子切换）

# 目录布局只有一份实现（ssotlib.index.layout）；这里保留同名别名供既有调用点使用。
active_version = _layout.active_version
resolve_db = _layout.resolve_db
list_versions = _layout.list_versions
write_root_manifest = _layout.write_root_manifest
set_active = _layout.set_active
prune_versions = _layout.prune_versions

API = _embed.API
DOC_PREFIX = _embed.DOC_PREFIX
RUN_META = {}
CLASS_BY_REL = {}
REASON_BY_REL = {}
SID_BY_REL = {}
CLASS_BY_DIR = {}
SID_BY_DIR = {}
SKIPPED = []
POLICY = {}
RETIRED = set()


def _profile_client():
    try:
        with open(PROFILE, encoding='utf-8') as f:
            c = json.load(f).get('client') or {}
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def _clamp_int(v, lo, hi, default):
    try:
        v = int(v)
    except Exception:
        return default
    return max(lo, min(hi, v))


def resolve_batch():
    """优先级：SP_INDEX_BATCH > profile.client.batch > 32。"""
    env = os.environ.get('SP_INDEX_BATCH')
    if env:
        return _clamp_int(env, 8, 512, 32), 'env'
    v = _profile_client().get('batch')
    if v is not None:
        return _clamp_int(v, 8, 512, 32), 'profile'
    return 32, 'default'


def resolve_workers():
    """workers 只登记不启用：03 号补充实测 8 路并发为负收益，默认 1。"""
    env = os.environ.get('SP_INDEX_WORKERS')
    if env:
        return _clamp_int(env, 1, 8, 1), 'env'
    v = _profile_client().get('workers')
    if v is not None:
        return _clamp_int(v, 1, 8, 1), 'profile'
    return 1, 'default'


BATCH, BATCH_SOURCE = resolve_batch()
WORKERS, WORKERS_SOURCE = resolve_workers()

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
        pack_vecs, pack_ids = _pack.pack_paths(DB)
        if '--full-pack' in sys.argv:
            n, secs = _pack.build_pack(DB, pack_vecs, pack_ids)
            print(f'向量包: 全量重建 {n} 行（{secs:.0f}s）', flush=True)
            return
        r = _pack.build_pack_incremental(DB, pack_vecs, pack_ids)
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


def write_build(preserve_policy=False):
    """索引新鲜度戳：commit + 块数 + 生成时间 + 契约 schema（供 sp_semantic/ssot_check/SSOT_REPORT 读）。

    schema 必须由生成器自己盖（契约 v2 · m0002 的章会被下次重建抹掉，见 A530）。
    preserve_policy：--pack-only/--fts-only 不重新计算 policy（否则会把 skipped 读数抹成 0）。
    """
    old = {}
    target = os.path.join(os.path.dirname(DB), 'BUILD.json')
    if preserve_policy:
        try:
            old = json.load(open(target, encoding='utf-8'))
        except Exception:
            old = {}
    try:
        con = sqlite3.connect(DB, timeout=30)
        n = con.execute('select count(*) from chunks').fetchone()[0]
        con.close()
    except Exception:
        n = 0
    data = {'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'commit': git_commit(), 'chunks': n, 'root': SSOT,
            'config': {'batch': BATCH, 'batch_source': BATCH_SOURCE,
                       'workers': WORKERS, 'workers_source': WORKERS_SOURCE},
            'policy': {'enabled': bool(POLICY.get('enabled')),
                       'include': POLICY.get('include') or [],
                       'skip': POLICY.get('skip') or [],
                       'skipped_sources': len(POLICY_SKIPPED),
                       'skipped_blocks': sum(x['blocks'] for x in POLICY_SKIPPED),
                       'retired_sources': len(RETIRED),
                       'cli_skipped_sources': len(SKIPPED)}}
    try:
        data['db_bytes'] = os.path.getsize(DB)
        data['pack_bytes'] = sum(os.path.getsize(os.path.join(os.path.dirname(DB), f))
                                 for f in ('pack-vecs.f32', 'pack-ids.i64')
                                 if os.path.exists(os.path.join(os.path.dirname(DB), f)))
    except OSError:
        pass
    schema = contract_schema()
    if schema:
        data['schema'] = schema
    try:
        env = sp_fingerprint.env()
        data.update({'model_fp': env['model_fp'], 'llama_version': env['llama_version'],
                     'backend': env['backend'], 'hardware_fp': env['hardware_fp']})
    except Exception:
        pass
    if RUN_META:
        data['run'] = dict(RUN_META)
        sec = RUN_META.get('seconds') or 0
        emb = RUN_META.get('embedded') or 0
        # 小增量（<50 块）的“吞吐”由固定开销主导，记录反而误导；只记完整构建或成规模增量
        if sec > 0 and emb and (RUN_META.get('mode') == 'full' or emb >= 50):
            data['throughput_chunks_per_s'] = round(emb / sec, 1)
    if preserve_policy and old:
        for k in ('policy', 'run', 'throughput_chunks_per_s'):
            if k in old:
                data[k] = old[k]
    try:
        with open(target, 'w', encoding='utf-8') as f:
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
    return [f for f in fs if os.path.isfile(f) and os.path.abspath(f) != os.path.abspath(ASSERT)]


def _assert_meta():
    try:
        d = json.load(open(ASSERT_META_PATH, encoding='utf-8'))
        return d.get('entries') or {}
    except Exception:
        return {}


def assertion_groups():
    """assertions.md：一条 ## A 一块（超 1400 字二次切），附带 status/superseded_by。"""
    import hashlib
    blocks = sp_assert_lib.parse(ASSERT)
    if not blocks:
        return []
    meta = _assert_meta()
    rel = os.path.relpath(ASSERT, SSOT)
    rows = []
    counts = {}
    for b in blocks:
        m = meta.get(b['id']) or {}
        status = str(m.get('status') or b.get('status') or 'unknown')
        sup = m.get('superseded_by') or b.get('superseded_by') or None
        counts[status] = counts.get(status, 0) + 1
        if status == 'vacant':
            continue
        text = b['text']
        parts = []
        if len(text) <= 1400:
            parts = [text]
        else:
            for i in range(0, len(text), 1400):
                p = text[i:i + 1400]
                if i:
                    p = f"[{b['id']} 续] " + p
                parts.append(p)
        ASSERT_META[(rel, b['line'])] = (b['id'], status, sup)
        for p in parts:
            rows.append((b['line'], p, 'assertion', ''))
    if not rows:
        return []
    try:
        mh = hashlib.md5(open(ASSERT_META_PATH, 'rb').read()).hexdigest()
    except OSError:
        mh = '-'
    digest = S1VER + ':assert:' + md5_files(ASSERT) + ':' + mh
    return [(rel, digest, rows)]


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
                rel = os.path.relpath(jl, SSOT)
                cls = sp_policy.class_of(meta)
                sid = sp_policy.sid_of(meta, rel)
                CLASS_BY_REL[rel] = cls
                REASON_BY_REL[rel] = str(meta.get('class_reason') or '')
                SID_BY_REL[rel] = sid
                CLASS_BY_DIR[os.path.basename(d)] = cls
                SID_BY_DIR[os.path.basename(d)] = sid
                groups.append((rel, digest, rows))
    return groups


def sa_groups():
    """子 agent 派生层（S1-subagents）：A 档 subagents.md + B 档 <stem>.jsonl"""
    groups = []
    for top in sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-subagents'))):
        for d in sorted(glob.glob(os.path.join(top, '*'))):
            if not os.path.isdir(d):
                continue
            pdir = os.path.basename(d)
            cls = CLASS_BY_DIR.get(pdir, 'human')
            sid = SID_BY_DIR.get(pdir, pdir[:8])
            def add(rel, digest, rows):
                CLASS_BY_REL[rel] = cls
                REASON_BY_REL[rel] = 'parent-session'
                SID_BY_REL[rel] = sid
                groups.append((rel, digest, rows))
            smd = os.path.join(d, 'subagents.md')
            if os.path.isfile(smd):
                chunks = chunk_file(smd)
                if chunks:
                    add(os.path.relpath(smd, SSOT), S1VER + ':' + md5_files(smd), chunks)
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
                    add(os.path.relpath(jf, SSOT), S1VER + ':' + md5_files(jf), rows)
    return groups


POLICY_SKIPPED = []
ASSERT = os.path.join(SSOT, 'knowledge', 'assertions.md')
ASSERT_META_PATH = os.path.join(SSOT, 'knowledge', 'assertions.meta.json')
ASSERT_META = {}
ASSERT_STATUS = {}
ASSERT_COUNTS = {}


def filter_groups(groups, policy, retired, all_classes=False, only=None, include_retired=False):
    keep, skipped = [], []
    for g in groups:
        rel = g[0]
        cls = CLASS_BY_REL.get(rel)
        if cls is None:                     # 非会话文件（START/lines/knowledge）不受 class 影响
            keep.append(g)
            continue
        sid = SID_BY_REL.get(rel)
        reason = ''
        if sid in retired and not include_retired:
            reason = 'retired'
        elif not sp_policy.included(cls, policy, all_classes, only):
            reason = REASON_BY_REL.get(rel) or ('class=' + cls)
        if reason:
            skipped.append({'path': rel, 'class': cls, 'sid': sid,
                            'reason': reason, 'blocks': len(g[2])})
        else:
            keep.append(g)
    return keep, skipped


def apply_policy(con, skipped, operator='sp_index'):
    """删除 policy 跳过的源块 + src_state；返回删掉的块数。"""
    n = 0
    paths = []
    for x in skipped:
        p = x['path']
        if p.endswith('/transcript.jsonl'):
            paths.append(p)
        elif p.endswith('/subagents.md') or p.endswith('.jsonl'):
            paths.append(p)
    for p in paths:
        n += con.execute('select count(*) from chunks where path=?', (p,)).fetchone()[0]
        con.execute('delete from chunks where path=?', (p,))
        con.execute('delete from src_state where path=?', (p,))
    con.commit()
    try:
        os.makedirs(os.path.join(SSOT, 'logs'), exist_ok=True)
        with open(os.path.join(SSOT, 'logs', 'index-ops.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                                'op': 'apply-policy', 'version': active_version(),
                                'db': DB, 'operator': operator,
                                'paths': paths, 'blocks_removed': n}, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return n


def embed_batch(texts, timeout=300):
    return _embed.embed_batch(texts, timeout=timeout, api=API)


def pack_norm(vec):
    import math
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return struct.pack(f'<{len(vec)}f', *[x / n for x in vec])


def chunk_meta(path, line):
    return ASSERT_META.get((path, line), (None, None, None))


def ensure_assertion_columns(con):
    try:
        cols = {r[1] for r in con.execute('pragma table_info(chunks)').fetchall()}
    except Exception:
        return
    for c in ('assertion_id', 'status', 'superseded_by'):
        if c not in cols:
            con.execute(f'alter table chunks add column {c} text')


def embed_and_store(con, todo, blocks, t0):
    ensure_assertion_columns(con)
    flat = [(g, r) for g in todo for r in blocks[g]]
    if flat:
        for i in range(0, len(flat), BATCH):
            batch = flat[i:i + BATCH]
            vecs = embed_batch([DOC_PREFIX + b[1][1] for b in batch])
            con.executemany(
                'insert into chunks(path,line,text,role,ts,vec,assertion_id,status,superseded_by) '
                'values(?,?,?,?,?,?,?,?,?)',
                [(b[0], b[1][0], b[1][1], b[1][2], b[1][3], pack_norm(v), *chunk_meta(b[0], b[1][0]))
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
    ensure_assertion_columns(con)
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
            'insert into chunks(path,line,text,role,ts,vec,assertion_id,status,superseded_by) '
            'values(?,?,?,?,?,?,?,?,?)',
            [(*r, *chunk_meta(r[0], r[1])) for r in reused_rows])
        con.commit()
    if flat:
        for i in range(0, len(flat), BATCH):
            batch = flat[i:i + BATCH]
            vecs = embed_batch([DOC_PREFIX + b[1][1] for b in batch])
            con.executemany(
                'insert into chunks(path,line,text,role,ts,vec,assertion_id,status,superseded_by) '
                'values(?,?,?,?,?,?,?,?,?)',
                [(b[0], b[1][0], b[1][1], b[1][2], b[1][3], pack_norm(v), *chunk_meta(b[0], b[1][0]))
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
    global DB, POLICY, RETIRED, SKIPPED, POLICY_SKIPPED
    POLICY = sp_policy.load_policy(SSOT)
    RETIRED, _retired_events = sp_policy.load_retired(SSOT)
    START_GEN = int(sp_pending.load().get('generation') or 0)
    if '--status' in sys.argv:
        # 只读：放在实例锁之前，构建进行中也能查版本与块数
        print("active: %s" % (active_version() or '(legacy index.db)'))
        print("db    : %s" % resolve_db())
        print("config: batch=%d(%s) workers=%d(%s) profile=%s" % (
            BATCH, BATCH_SOURCE, WORKERS, WORKERS_SOURCE,
            PROFILE if os.path.exists(PROFILE) else '-'))
        print("policy: %s" % sp_policy.summary(POLICY, len(RETIRED)))
        try:
            env = sp_fingerprint.env()
            mfp = env['model_fp']
            bp = os.path.join(os.path.dirname(resolve_db()), 'BUILD.json')
            b = json.load(open(bp, encoding='utf-8')) if os.path.exists(bp) else {}
            old = b.get('model_fp')
            print("model : fp=%s [hard]%s" % (
                mfp, (f"  ⚠ changed (BUILD={old}) → 需 --full 重建" if old and old != mfp else '')))
            print("env   : %s · %s · %s [soft: 只影响性能/bench，不失效向量]" % (
                env['hardware_fp'], env['backend'], env['llama_version']))
        except Exception:
            pass
        if WORKERS > 1:
            print("note  : workers>1 仅登记，未启用（03 号负结果；默认 1）")
        for name, st, n, m in list_versions():
            print("  %-30s %-10s chunks=%-7s %s" % (
                name, st, n, datetime.datetime.fromtimestamp(m).strftime('%m-%d %H:%M')))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_contract import guard as _contract_guard
    args = sys.argv[1:]
    if not _contract_guard('sp_index', write=('--plan' not in args)):
        return 2
    # 实例锁（2026-10-15）：增量/全量互斥——防 launchd 值守与手动跑并发双写（曾致重复块，见当日去重记录）
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    lock_fd = os.open(os.path.join(os.path.dirname(DB), '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    if not _try_lock(lock_fd):
        return 3
    t0 = time.time()

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
        write_build(preserve_policy=True)
        try:
            os.close(lock_fd)       # 让 plan 子进程能拿锁
        except Exception:
            pass
        sp_pending.clear_pack_stale_if_settled()
        return
    if '--fts-only' in sys.argv:
        if not os.path.exists(DB):
            sys.exit('索引不存在——先跑全量')
        con = sqlite3.connect(DB, timeout=30)
        ensure_fts(con, rebuild=True)
        con.commit()
        con.close()
        write_build(preserve_policy=True)
        print('✅ FTS trigram 重建完成')
        return
    inc = ('--incremental' in args) or not ('--build' in args or '--full' in args)
    only_classes = None
    for i, x in enumerate(args):
        if x == '--class' and i + 1 < len(args):
            only_classes = set(v.strip() for v in args[i + 1].split(',') if v.strip())
        elif x.startswith('--class='):
            only_classes = set(v.strip() for v in x.split('=', 1)[1].split(',') if v.strip())
    all_classes = '--all-classes' in args
    include_retired = '--include-retired' in args

    CLASS_BY_REL.clear(); REASON_BY_REL.clear(); SID_BY_REL.clear()
    CLASS_BY_DIR.clear(); SID_BY_DIR.clear(); ASSERT_META.clear()
    fg = file_groups()
    ag = assertion_groups()
    sg = s1_groups()
    sas = sa_groups()
    all_groups = fg + ag + sg + sas
    # policy 级跳过（不受 --class/--all-classes 影响；用于 --apply-policy 和观测）
    _, POLICY_SKIPPED = filter_groups(all_groups, POLICY, RETIRED, False, None, False)
    groups, SKIPPED = filter_groups(all_groups, POLICY, RETIRED,
                                    all_classes, only_classes, include_retired)

    if '--plan' in args:
        db = resolve_db()
        prev = {}
        would = 0
        if os.path.exists(db):
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            try:
                prev = dict(con.execute('select path,digest from src_state').fetchall())
            except Exception:
                prev = {}
            for x in POLICY_SKIPPED:
                p = x['path']
                if os.path.basename(p) in ('transcript.jsonl', 'subagents.md') or p.endswith('.jsonl'):
                    would += con.execute('select count(*) from chunks where path=?', (p,)).fetchone()[0]
            con.close()
        pending = [g for g in groups if prev.get(g[0]) != g[1]]
        out = {'db': db, 'policy': sp_policy.summary(POLICY, len(RETIRED)),
               'include_sources': len(groups),
               'include_blocks': sum(len(g[2]) for g in groups),
               'skip_sources': len(SKIPPED),
               'skip_blocks': sum(x['blocks'] for x in SKIPPED),
               'pending_sources': len(pending),
               'pending_blocks': sum(len(g[2]) for g in pending),
               'would_remove': would}
        if '--json' in args:
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 0
        print(f"policy: {out['policy']}")
        print(f"include: {out['include_sources']} 源 / {out['include_blocks']} 块")
        print(f"skip:    {out['skip_sources']} 源 / {out['skip_blocks']} 块")
        for x in SKIPPED[:100]:
            print(f"  - {x['sid'][:8]} [{x['class']}] {x['reason']} · {x['path']} ({x['blocks']} 块)")
        if len(SKIPPED) > 100:
            print(f"  … 其余 {len(SKIPPED) - 100} 源")
        print(f"pending: {out['pending_sources']} 源 / {out['pending_blocks']} 块")
        print(f"would remove: {would} 块（--apply-policy）")
        return 0

    if '--apply-policy' in args:
        db = resolve_db()
        if not os.path.exists(db):
            sys.exit('索引不存在——无可清理')
        con = sqlite3.connect(db, timeout=30)
        n = apply_policy(con, POLICY_SKIPPED)
        con.close()
        try:
            write_build()
        except Exception:
            pass
        print(f"✅ apply-policy：清理 {len(POLICY_SKIPPED)} 源 / {n} 块（向量包需 --pack-only 压实）")
        return 0

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
    print(f'语料：{len(groups)} 源 / {total} 块（文件 {len(fg)} / 断言 {len(ag)} / 会话 {len(sg)} / 子agent {len(sas)}）', flush=True)
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    if not inc:
        con = sqlite3.connect(DB, timeout=30)
        for t in ('chunks_ai', 'chunks_ad', 'chunks_au'):
            con.execute(f'drop trigger if exists {t}')
        con.execute('drop table if exists chunks_fts')
        con.execute('drop table if exists chunks')
        con.execute('create table chunks(id integer primary key, path text, line integer, '
                    'text text, role text, ts text, vec blob, '
                    'assertion_id text, status text, superseded_by text)')
        con.execute('drop table if exists src_state')
        con.execute('create table src_state(path text primary key, digest text)')
        n = embed_and_store(con, [g[0] for g in groups], blocks, t0)
        RUN_META.clear()
        RUN_META.update({'mode': 'full', 'embedded': n, 'reused': 0,
                         'seconds': round(time.time() - t0, 1)})
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
        sp_pending.after_index(START_GEN, '--no-pack' in sys.argv, n > 0)
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
    ensure_assertion_columns(con)
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
            sp_pending.after_index(START_GEN, '--no-pack' in sys.argv, False)
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
    RUN_META.clear()
    RUN_META.update({'mode': 'incremental', 'embedded': n, 'reused': reused,
                     'seconds': round(time.time() - t0, 1)})
    con.executemany('insert or replace into src_state(path,digest) values(?,?)',
                    [(p, digests[p]) for p in todo])
    con.commit()
    con.close()
    if '--no-pack' in sys.argv:
        print('向量包: 跳过（--no-pack；语义检索暂时看不到本次新增内容）', flush=True)
    else:
        refresh_pack()
    write_build()
    sp_pending.after_index(START_GEN, '--no-pack' in sys.argv, n > 0)
    print(f'✅ 增量完成：新嵌 {n} 块 / 复用 {reused} 块（{len(todo)} 源）  用时 {time.time() - t0:.0f}s')


if __name__ == '__main__' and ('--help' in sys.argv or '-h' in sys.argv):
    print(__doc__)
    raise SystemExit(0)

if __name__ == '__main__':
    sys.exit(main())

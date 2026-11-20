"""向量包：pack-vecs.f32 + pack-ids.i64（mmap 快查 / 增量追加 / 过期压实）。

numpy 只在真正需要读写向量包时导入——kit 的核心工具装完不跑索引时
不需要第三方依赖（守住「纯标准库」的安装面）。
"""
import os
import shutil
import sqlite3
import struct
import time

from .layout import pack_paths


def _paths(db, pack_vecs, pack_ids):
    d_v, d_i = pack_paths(db)
    return (pack_vecs or d_v, pack_ids or d_i)


def pack_fresh(db, pack_vecs=None, pack_ids=None):
    """包是否比库新（库更新过就需要重建/追加）。"""
    pack_vecs, pack_ids = _paths(db, pack_vecs, pack_ids)
    try:
        return (os.path.exists(pack_vecs) and os.path.exists(pack_ids)
                and os.path.getmtime(pack_vecs) >= os.path.getmtime(db))
    except OSError:
        return False


def build_pack(db, pack_vecs=None, pack_ids=None, quiet=False):
    """把 chunks 的向量抽成 mmap 友好的 pack-vecs.f32 + pack-ids.i64。返回 (行数, 秒)。"""
    pack_vecs, pack_ids = _paths(db, pack_vecs, pack_ids)
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


def build_pack_incremental(db, pack_vecs=None, pack_ids=None, quiet=False,
                           max_stale=2000, max_missing=5000):
    """增量追加 pack；stale/缺失过多时回退全量重建（压实）。

    设计：pack 允许保留已删除行的旧向量（搜索取详情时会跳过），
    但 stale 超过 max_stale 或一次缺太多时，做一次全量压实。
    返回 dict：mode=noop|append|rebuild, n, appended, stale, secs。
    """
    import numpy as np

    pack_vecs, pack_ids = _paths(db, pack_vecs, pack_ids)
    t0 = time.time()
    if not (os.path.exists(db) and os.path.exists(pack_vecs) and os.path.exists(pack_ids)):
        n, secs = build_pack(db, pack_vecs, pack_ids, quiet=quiet)
        return {'mode': 'rebuild', 'n': n, 'appended': 0, 'stale': 0, 'secs': secs}
    ids = np.fromfile(pack_ids, dtype=np.int64)
    if not len(ids):
        n, secs = build_pack(db, pack_vecs, pack_ids, quiet=quiet)
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
        n, secs = build_pack(db, pack_vecs, pack_ids, quiet=quiet)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
    total = os.path.getsize(pack_vecs) // 4
    if total % len(ids):
        con.close()
        n, secs = build_pack(db, pack_vecs, pack_ids, quiet=quiet)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
    dim = total // len(ids)
    q = ','.join('?' * len(missing))
    rows = con.execute(f'select id, vec from chunks where id in ({q}) order by id',
                       [int(x) for x in missing]).fetchall()
    con.close()
    if len(rows) != len(missing) or any(len(v) // 4 != dim for _rid, v in rows):
        n, secs = build_pack(db, pack_vecs, pack_ids, quiet=quiet)
        return {'mode': 'rebuild', 'n': n, 'appended': 0,
                'stale': 0, 'secs': secs}
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


def load_pack(pack_vecs, pack_ids):
    """→ (memmap(N,dim), int64[N])；不可用时 (None, None)。"""
    import numpy as np

    try:
        ids = np.fromfile(pack_ids, dtype=np.int64)
        total = os.path.getsize(pack_vecs) // 4
        if not len(ids) or total % len(ids):
            return (None, None)
        M = np.memmap(pack_vecs, dtype=np.float32, mode='r').reshape(len(ids), total // len(ids))
        return (M, ids)
    except Exception:
        return (None, None)

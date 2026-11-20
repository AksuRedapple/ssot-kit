"""索引目录布局：版本目录、active 指针、根 BUILD 清单（唯一实现）。

版本化布局（2026-11 起）：
  S2-index/semantic/
    index.db                 legacy 单库（兜底，不再新建）
    active.json              唯一在线指针
    BUILD.json               在线清单（daemon 盯 mtime 决定 reload）
    versions/<ver>/index.db  每次全量构建一个版本
    versions/<ver>/BUILD.json
    versions/<ver>/STATUS    building|ready|active|retired
"""
import datetime
import os
import shutil
import sqlite3
import time

from .. import store

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
SEM = os.path.join(SSOT, 'S2-index', 'semantic')
VERS = os.path.join(SEM, 'versions')
ACTIVE = os.path.join(SEM, 'active.json')
LEGACY_DB = os.path.join(SEM, 'index.db')

PACK_VECS_NAME = 'pack-vecs.f32'
PACK_IDS_NAME = 'pack-ids.i64'


def _sem(sem=None):
    return sem or SEM


def active_version(sem=None):
    """读 active.json；指向的版本不存在就当没有（回退 legacy）。"""
    sem = _sem(sem)
    try:
        v = store.read_json(os.path.join(sem, 'active.json'), {}).get('version')
        if v and os.path.exists(os.path.join(sem, 'versions', v, 'index.db')):
            return v
    except Exception:
        pass
    return None


def resolve_db(sem=None):
    """当前在线库路径：active 版本优先，否则 legacy 单库。"""
    sem = _sem(sem)
    v = active_version(sem)
    return os.path.join(sem, 'versions', v, 'index.db') if v else os.path.join(sem, 'index.db')


def version_dir(ver, sem=None):
    return os.path.join(_sem(sem), 'versions', ver)


def list_versions(sem=None):
    """→ [(name, status, chunks, mtime)]；chunks=-1 表示库不可读。"""
    sem = _sem(sem)
    vers = os.path.join(sem, 'versions')
    out = []
    if os.path.isdir(vers):
        for name in sorted(os.listdir(vers)):
            d = os.path.join(vers, name)
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


def write_root_manifest(ver, sem=None):
    """根 BUILD.json = 在线清单（daemon 盯它的 mtime 决定 reload）。"""
    sem = _sem(sem)
    data = store.read_json(os.path.join(sem, 'versions', ver, 'BUILD.json'), {}) or {}
    data.update({'active': ver, 'db': os.path.join('versions', ver, 'index.db'),
                 'activated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')})
    store.write_json_atomic(os.path.join(sem, 'BUILD.json'), data, indent=2, mode=0o644)


def set_active(ver, sem=None):
    """原子切换 active 指针，并维护各版本 STATUS。"""
    sem = _sem(sem)
    store.write_json_atomic(
        os.path.join(sem, 'active.json'),
        {'version': ver, 'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds')},
        indent=None, mode=0o644)
    try:
        open(os.path.join(sem, 'versions', ver, 'STATUS'), 'w', encoding='utf-8').write('active\n')
    except Exception:
        pass
    for name, st, _n, _m in list_versions(sem):
        if name != ver and st == 'active':
            try:
                open(os.path.join(sem, 'versions', name, 'STATUS'), 'w', encoding='utf-8').write('retired\n')
            except Exception:
                pass
    write_root_manifest(ver, sem)


def prune_versions(keep=2, sem=None):
    """保留最近 keep 个 ready 版本（active 永远保留）+ 清掉 >7 天的 retired。"""
    sem = _sem(sem)
    vers = os.path.join(sem, 'versions')
    # 顺手清掉中断留下的 .building（超过 1 天的），它们是构建残骸不是版本
    for name, st, _n, m in list_versions(sem):
        if name.endswith('.building') and (time.time() - m) > 86400:
            shutil.rmtree(os.path.join(vers, name), ignore_errors=True)
    vs = [v for v in list_versions(sem) if v[1] != 'building']
    vs.sort(key=lambda x: x[3], reverse=True)
    act = active_version(sem)
    removed = []
    for i, (name, st, _n, m) in enumerate(vs):
        if name == act:
            continue
        if i < keep and (time.time() - m) < 7 * 86400:
            continue
        shutil.rmtree(os.path.join(vers, name), ignore_errors=True)
        removed.append(name)
    return removed


def pack_paths(db):
    """向量包固定放在库同目录（与版本库一一对应）。"""
    d = os.path.dirname(db)
    return (os.path.join(d, PACK_VECS_NAME), os.path.join(d, PACK_IDS_NAME))

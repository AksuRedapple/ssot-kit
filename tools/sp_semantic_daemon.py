#!/usr/bin/env python3
"""sp_semantic_daemon · 常驻检索服务(把"每次搬 804MB"改成"搬一次")

设计:drafts/m2-semantic-daemon/SPEC.md
- unix socket ~/.ssot/semantic.sock,行式 JSON
- 启动时预热 pack(顺序读一遍,把页灌进 page cache)
- 每请求调 sp_semantic.run_search(保证与一次性路径**逐字节同源**)
- 盯 BUILD.json mtime,变化即记 reload(结果自然反映新 pack)
- 请求可带 vec(跳过编码),用于拆"检索段/端到端"两个口径

用法:
  sp_semantic_daemon.py [--socket PATH] [--prewarm] [--debug]
请求: {"query": "...", "top": 8, "expand": false, "mode": "dense"} 或 {"vec": [...], ...}
响应: {"ok": true, "results": [...], "meta": {...}, "ms": 123}
"""
import argparse, datetime, hashlib, importlib.util, json, numpy as np, os, resource, signal, socket, socketserver, sys, threading, time
from ssotlib import cli  # noqa: E402
from ssotlib.index import layout as _layout, pack as _pack  # noqa: E402

SSOT = os.path.expanduser('~/ssot')
PACK = os.path.join(SSOT, 'S2-index/semantic/pack-vecs.f32')
BUILD = os.path.join(SSOT, 'S2-index/semantic/BUILD.json')
SOCK = os.environ.get('SSOT_SEMANTIC_SOCKET', os.path.expanduser('~/.ssot/semantic.sock'))
STATE_PATH = os.environ.get('SSOT_SEMANTIC_STATE', '/tmp/ssot-semantic.state.json')
LOG = os.path.join(SSOT, 'logs', 'semantic-daemon.log')
LIFECYCLE_LOG = os.environ.get('SSOT_SEMANTIC_LIFECYCLE_LOG',
                               os.path.join(SSOT, 'logs', 'semantic-lifecycle.jsonl'))


def load_sem():
    spec = importlib.util.spec_from_file_location('sp_semantic', os.path.join(SSOT, 'tools/sp_semantic.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SEM = None
SERVER = None
STATE = {'build_mtime': 0, 'generation': '', 'db': '', 'reloads': 0, 'prewarm_ms': 0,
         'reloading': False, 'active': 0, 'last_query': time.time(),
         'started_at': time.time(), 'stopping': False, 'stop_watcher': False}
STATE_LOCK = threading.Lock()
RELOAD_LOCK = threading.Lock()


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%F %T")} {msg}\n')


def lifecycle(event, **fields):
    os.makedirs(os.path.dirname(LIFECYCLE_LOG), exist_ok=True)
    rec = {'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
           'event': event, 'pid': os.getpid(), **fields}
    with open(LIFECYCLE_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def write_state_locked():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = f'{STATE_PATH}.{os.getpid()}.tmp'
    rec = {k: STATE[k] for k in ('active', 'last_query', 'started_at', 'reloading',
                                  'stopping', 'generation', 'db')}
    rec['pid'] = os.getpid()
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_PATH)


def write_state():
    with STATE_LOCK:
        write_state_locked()


def mark_query():
    with STATE_LOCK:
        STATE['last_query'] = time.time()
        write_state_locked()


def _stat(path):
    try:
        st = os.stat(path)
        return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns}
    except OSError:
        return None


def resolve_generation():
    """解析当前 active 代际；DB 与 pack 必须来自同一版本目录。"""
    sem = os.path.join(SSOT, 'S2-index', 'semantic')
    db = _layout.resolve_db(sem)
    build = os.path.join(os.path.dirname(db), 'BUILD.json')
    pack_vecs, pack_ids = _pack.pack_paths(db)
    # 兼容旧测试/legacy：没有版本库时允许显式 PACK 常量。
    if not os.path.exists(db) and os.path.exists(PACK):
        pack_vecs = PACK
        pack_ids = os.path.join(os.path.dirname(PACK), 'pack-ids.i64')
        build = BUILD
    try:
        with open(build, encoding='utf-8') as f:
            build_data = json.load(f)
    except Exception:
        build_data = {}
    payload = {'db': os.path.realpath(db), 'build': build_data,
               'db_stat': _stat(db), 'pack_vecs_stat': _stat(pack_vecs),
               'pack_ids_stat': _stat(pack_ids)}
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {'db': db, 'build': build, 'pack_vecs': pack_vecs, 'pack_ids': pack_ids,
            'fingerprint': fingerprint}


def apply_generation(gen, pack_override=None):
    """原子切换 DB/pack 路径与内存包；查询与加载共用同一把锁。"""
    with RELOAD_LOCK:
        SEM.DB = gen['db']
        SEM.BUILD = gen['build']
        SEM.PACK_VECS = gen['pack_vecs']
        SEM.PACK_IDS = gen['pack_ids']
        if pack_override is not None:
            SEM._PACK_OVERRIDE = pack_override
        STATE['generation'] = gen['fingerprint']
        STATE['db'] = gen['db']


def load_into_ram(gen=None):
    """整包读进匿名内存；读完后在同一临界区切换 DB 与 pack。"""
    gen = gen or resolve_generation()
    t0 = time.time()
    ids = np.fromfile(gen['pack_ids'], dtype=np.int64)
    total = os.path.getsize(gen['pack_vecs']) // 4
    M = np.fromfile(gen['pack_vecs'], dtype=np.float32).reshape(len(ids), total // len(ids))
    apply_generation(gen, (M, ids))
    STATE['prewarm_ms'] = int((time.time() - t0) * 1000)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024
    log(f'ram-load {len(ids)} rows gen={gen["fingerprint"]} '
        f'in {STATE["prewarm_ms"]}ms rss={rss:.0f}MB')
    print(f'ram-load {len(ids)} rows gen={gen["fingerprint"]} '
          f'in {STATE["prewarm_ms"]}ms rss={rss:.0f}MB', flush=True)


def maybe_reload():
    gen = resolve_generation()
    fp = gen['fingerprint']
    if fp == STATE['generation']:
        return
    with STATE_LOCK:
        if STATE['reloading']:
            return
        STATE['reloading'] = True
        STATE['reloads'] += 1
        write_state_locked()
    log(f'reload: {STATE["generation"] or "none"} → {fp}')
    STATE['build_mtime'] = _stat(gen['build'])['mtime_ns'] if _stat(gen['build']) else 0

    def _bg():
        try:
            load_into_ram(gen)
            log('reload done')
        except Exception as e:
            log(f'reload FAIL {e}')
        finally:
            with STATE_LOCK:
                STATE['reloading'] = False
                write_state_locked()
    threading.Thread(target=_bg, daemon=True).start()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        with STATE_LOCK:
            if STATE['stopping']:
                return
            STATE['active'] += 1
            write_state_locked()
        try:
            for raw in self.rfile:
                t0 = time.time()
                mark_query()
                try:
                    req = json.loads(raw.decode('utf-8'))
                except Exception as e:
                    self.wfile.write((json.dumps({'ok': False, 'error': f'bad json: {e}'}) + '\n').encode())
                    continue
                maybe_reload()
                try:
                    with RELOAD_LOCK:
                        if 'vec' in req:
                            res, meta = SEM.run_search_by_vec(req['vec'], top=int(req.get('top', 8)),
                                                              path=req.get('path'), role=req.get('role'))
                        else:
                            res, meta = SEM.run_search(req['query'], top=int(req.get('top', 8)),
                                                       path=req.get('path'), role=req.get('role'),
                                                       expand=bool(req.get('expand')),
                                                       mode=req.get('mode', 'dense'))
                    out = {'ok': True, 'results': res, 'meta': meta, 'ms': int((time.time() - t0) * 1000),
                           'reloads': STATE['reloads']}
                except Exception as e:
                    out = {'ok': False, 'error': f'{type(e).__name__}: {e}', 'ms': int((time.time() - t0) * 1000)}
                try:
                    self.wfile.write((json.dumps(out, ensure_ascii=False) + '\n').encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                if 'ms' in out:
                    log(f'query ms={out["ms"]} top={req.get("top")} vec={"vec" in req} ok={out["ok"]}')
        finally:
            with STATE_LOCK:
                STATE['active'] = max(0, STATE['active'] - 1)
                write_state_locked()


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def _finish_after_drain():
    while True:
        with STATE_LOCK:
            if STATE['active'] == 0 and not STATE['reloading']:
                break
        time.sleep(0.1)
    if SERVER is not None:
        SERVER.shutdown()


def terminate(signum, frame):
    start_watcher = False
    with STATE_LOCK:
        STATE['stopping'] = True
        write_state_locked()
        deferred = STATE['active'] > 0 or STATE['reloading']
        active = STATE['active']
        reloading = STATE['reloading']
        if deferred and not STATE['stop_watcher']:
            STATE['stop_watcher'] = True
            start_watcher = True
    if deferred:
        lifecycle('term_deferred', active=active, reloading=reloading)
        log(f'term deferred active={active} reloading={reloading}')
        if start_watcher:
            threading.Thread(target=_finish_after_drain, daemon=True).start()
        return
    lifecycle('stopping', active=0, reloading=0)
    raise SystemExit(0)


def main():
    global SEM, SERVER
    ap = cli.base_parser(epilog='示例:\n  sp_semantic_daemon.py --prewarm\n  echo \'{"query":"跨机下发","top":5}\' | nc -U ~/.ssot/semantic.sock', root=False)
    ap.add_argument('--socket', default=SOCK)
    ap.add_argument('--prewarm', action='store_true', default=True)
    ap.add_argument('--no-prewarm', dest='prewarm', action='store_false')
    a = ap.parse_args()

    SEM = load_sem()
    os.makedirs(os.path.dirname(a.socket), exist_ok=True)
    if os.path.exists(a.socket):
        os.unlink(a.socket)
    gen = resolve_generation()
    if a.prewarm:
        load_into_ram(gen)
    else:
        apply_generation(gen)
    maybe_reload()

    STATE['started_at'] = time.time()
    STATE['last_query'] = time.time()
    signal.signal(signal.SIGTERM, terminate)
    srv = Server(a.socket, Handler)
    SERVER = srv
    os.chmod(a.socket, 0o600)
    write_state()
    lifecycle('started', prewarm_ms=STATE['prewarm_ms'], reloads=STATE['reloads'])
    log(f'listen {a.socket} prewarm={STATE["prewarm_ms"]}ms')
    print(f'listening on {a.socket}', flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        SERVER = None
        try:
            os.unlink(a.socket)
        except FileNotFoundError:
            pass
        lifecycle('stopped', active=STATE['active'], reloads=STATE['reloads'])


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

try:
    import numpy as np  # noqa: F401
except ImportError:
    print('SKIP: semantic daemon lifecycle test requires numpy')
    raise SystemExit(77)

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import sp_semantic_daemon as D  # noqa: E402
import sp_semantic as SEMCLI  # noqa: E402


class FakeSem:
    def run_search(self, query, **kw):
        return [{'path': 'lines/test.md', 'line': 1, 'score': 0.9}], {'mode': kw.get('mode', 'dense')}

    def run_search_by_vec(self, vec, **kw):
        return [{'path': 'lines/test.md', 'line': 1, 'score': 0.8}], {'mode': 'vec'}


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sock = str(self.root / 'sem.sock')
        self.state = str(self.root / 'state.json')
        self.lifecycle = str(self.root / 'lifecycle.jsonl')
        self.old = (D.STATE_PATH, D.LIFECYCLE_LOG, D.SEM, dict(D.STATE))
        D.STATE_PATH = self.state
        D.LIFECYCLE_LOG = self.lifecycle
        D.SEM = FakeSem()
        D.STATE.update(active=0, last_query=time.time() - 10, started_at=time.time() - 10,
                       reloading=False, stopping=False)
        self.srv = None
        self.thread = None
        self.procs = []

    def tearDown(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()
        if self.thread:
            self.thread.join(2)
        for proc in self.procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(2)
        D.STATE_PATH, D.LIFECYCLE_LOG, D.SEM, state = self.old
        D.STATE.clear()
        D.STATE.update(state)
        self.tmp.cleanup()

    def start_server(self):
        self.srv = D.Server(self.sock, D.Handler)
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        for _ in range(100):
            if os.path.exists(self.sock):
                return
            time.sleep(0.02)
        self.fail('socket not ready')

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(self.sock)
        return s

    def wait_state(self, pred):
        for _ in range(100):
            if os.path.exists(self.state):
                data = json.loads(Path(self.state).read_text())
                if pred(data):
                    return data
            time.sleep(0.02)
        self.fail('state condition not met')

    def test_active_and_last_query_state(self):
        self.start_server()
        D.write_state()
        held = self.connect()
        self.wait_state(lambda d: d['active'] == 1)
        held.sendall(b'{"query":"x","top":1}\n')
        buf = b''
        while b'\n' not in buf:
            buf += held.recv(65536)
        self.assertTrue(json.loads(buf.split(b'\n', 1)[0])['ok'])
        held.close()
        self.wait_state(lambda d: d['active'] == 0)
        self.assertGreater(json.loads(Path(self.state).read_text())['last_query'], time.time() - 5)

    def test_fetch_rows_default_follows_current_db(self):
        import sqlite3
        db1 = self.root / 'v1.db'
        db2 = self.root / 'v2.db'
        for db, text in ((db1, 'old'), (db2, 'new')):
            con = sqlite3.connect(db)
            con.execute('create table chunks(id integer primary key, path text, line integer, '
                        'text text, role text, ts text, assertion_id text, status text, '
                        'superseded_by text)')
            con.execute('insert into chunks values(1,?,?,?,?,?,?,?,?)',
                        ('lines/a.md', 1, text, 'user', '', None, 'active', None))
            con.commit()
            con.close()
        old = SEMCLI.DB
        try:
            SEMCLI.DB = str(db2)
            self.assertEqual(SEMCLI.fetch_rows([1])[1][2], 'new')
        finally:
            SEMCLI.DB = old

    def test_generation_switch_updates_db_and_pack_together(self):
        sem = self.root / 'S2-index' / 'semantic'
        for ver, value in (('v1', 1.0), ('v2', 2.0)):
            d = sem / 'versions' / ver
            d.mkdir(parents=True)
            (d / 'index.db').write_bytes(b'')
            (d / 'BUILD.json').write_text(json.dumps({'chunks': 1, 'ver': ver}),
                                          encoding='utf-8')
            np.array([1], dtype=np.int64).tofile(d / 'pack-ids.i64')
            np.array([value, value + 1], dtype=np.float32).tofile(d / 'pack-vecs.f32')
        (sem / 'active.json').write_text(json.dumps({'version': 'v1'}), encoding='utf-8')
        old = (D.SSOT, D.PACK, D.SEM)
        D.SSOT = str(self.root)
        D.PACK = str(sem / 'pack-vecs.f32')

        class FakeSem:
            _PACK_OVERRIDE = None

        D.SEM = FakeSem()
        try:
            gen1 = D.resolve_generation()
            D.load_into_ram(gen1)
            self.assertTrue(D.SEM.DB.endswith('/versions/v1/index.db'))
            self.assertTrue(D.SEM.PACK_VECS.endswith('/versions/v1/pack-vecs.f32'))
            self.assertEqual(float(D.SEM._PACK_OVERRIDE[0][0, 0]), 1.0)

            (sem / 'active.json').write_text(json.dumps({'version': 'v2'}), encoding='utf-8')
            gen2 = D.resolve_generation()
            self.assertNotEqual(gen1['fingerprint'], gen2['fingerprint'])
            D.load_into_ram(gen2)
            self.assertTrue(D.SEM.DB.endswith('/versions/v2/index.db'))
            self.assertTrue(D.SEM.PACK_VECS.endswith('/versions/v2/pack-vecs.f32'))
            self.assertEqual(float(D.SEM._PACK_OVERRIDE[0][0, 0]), 2.0)
            self.assertEqual(D.STATE['generation'], gen2['fingerprint'])
        finally:
            D.SSOT, D.PACK, D.SEM = old

    def test_sigterm_defers_while_active(self):
        self.start_server()
        D.write_state()
        held = self.connect()
        self.wait_state(lambda d: d['active'] == 1)
        D.terminate(15, None)
        # 新语义：先停止接单，再等待在途请求 drain；不能继续接受新连接。
        self.assertTrue(D.STATE['stopping'])
        held.close()
        self.wait_state(lambda d: d['active'] == 0)
        with self.assertRaises(SystemExit):
            D.terminate(15, None)
        self.assertTrue(D.STATE['stopping'])

    def fake_launchctl(self, running=True):
        bindir = self.root / 'bin'
        bindir.mkdir(exist_ok=True)
        script = bindir / 'launchctl'
        state = 'running' if running else 'not running'
        script.write_text(f'''#!/bin/bash
if [ "$1" = print ]; then
  echo "state = {state}"
  exit 0
fi
if [ "$1" = kill ]; then
  pid=$({sys.executable} -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$SSOT_SEMANTIC_STATE")
  kill -TERM "$pid"
  exit 0
fi
exit 1
''')
        script.chmod(0o755)
        return str(bindir)

    def start_dummy_socket(self, ignore_term=False):
        code = ('import signal,socket,sys,time; '
                + ('signal.signal(signal.SIGTERM, signal.SIG_IGN); ' if ignore_term else '')
                + 's=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); '
                  's.bind(sys.argv[1]); s.listen(5); time.sleep(60)')
        proc = subprocess.Popen([sys.executable, '-c', code, self.sock])
        self.procs.append(proc)
        for _ in range(100):
            if os.path.exists(self.sock):
                return proc
            time.sleep(0.02)
        self.fail('dummy socket not ready')

    def run_reaper(self, bindir, label='test.semantic', root=None, extra_env=None):
        env = os.environ.copy()
        env.update(PATH=bindir + ':' + env.get('PATH', ''),
                   SSOT_SEMANTIC_LABEL=label,
                   SSOT_SEMANTIC_LEASE=str(self.root / 'want'),
                   SSOT_SEMANTIC_STATE=self.state,
                   SSOT_SEMANTIC_SOCKET=self.sock,
                   SSOT_SEMANTIC_LIFECYCLE_LOG=self.lifecycle,
                   SSOT_SEMANTIC_LEASE_STALE_SEC='0',
                   SSOT_SEMANTIC_IDLE_SEC='0',
                   SSOT_SEMANTIC_TERM_WAIT_SEC='1')
        if root is not None:
            env['SSOT_ROOT'] = str(root)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(['/bin/bash', str(TOOLS / 'sp_semantic_reaper.sh')],
                              capture_output=True, text=True, env=env, timeout=15)

    def write_daemon_state(self, pid, active=0):
        Path(self.state).write_text(json.dumps({'pid': pid, 'active': active,
                                                'last_query': int(time.time()) - 10,
                                                'reloading': 0, 'stopping': 0}))

    def test_reaper_skips_active(self):
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=1)
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(self.root / 'want').exists())
        self.assertIsNone(proc.poll())
        self.assertIn('skip_active', Path(self.lifecycle).read_text())

    def test_reaper_restores_lease_on_query_race(self):
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()

        def arrive_during_grace():
            time.sleep(.3)
            data = json.loads(Path(self.state).read_text())
            data['last_query'] = int(time.time())
            Path(self.state).write_text(json.dumps(data))

        updater = threading.Thread(target=arrive_during_grace)
        updater.start()
        result = self.run_reaper(self.fake_launchctl())
        updater.join(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(self.root / 'want').exists())
        self.assertIsNone(proc.poll())
        text = Path(self.lifecycle).read_text()
        self.assertIn('skip_race', text)
        self.assertNotIn('reap_start', text)

    def test_reaper_skips_when_lease_arrives_during_grace(self):
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()

        def arrive_during_grace():
            time.sleep(.3)
            Path(self.root / 'want').touch()

        updater = threading.Thread(target=arrive_during_grace)
        updater.start()
        result = self.run_reaper(self.fake_launchctl())
        updater.join(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(self.root / 'want').exists())
        self.assertIsNone(proc.poll())
        text = Path(self.lifecycle).read_text()
        self.assertIn('skip_race', text)
        self.assertNotIn('reap_start', text)

    def test_reaper_reaps_idle(self):
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(self.root / 'want').exists())
        self.assertFalse(os.path.exists(self.sock))
        events = [json.loads(x) for x in Path(self.lifecycle).read_text().splitlines()]
        reaped = next(x for x in events if x.get('event') == 'reaped')
        self.assertGreaterEqual(reaped['idle_s'], 10)

    def test_production_reaper_triggers_observation(self):
        tools = self.root / 'tools'
        tools.mkdir()
        marker = self.root / 'observer.args'
        observer = tools / 'sp_semantic_observe.py'
        observer.write_text('import pathlib,sys\n'
                            f'pathlib.Path({str(marker)!r}).write_text(" ".join(sys.argv[1:]))\n')
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl(), label='com.ssot.semantic', root=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), '--trigger reap')

    def test_manual_reap_does_not_trigger_observation(self):
        tools = self.root / 'tools'
        tools.mkdir()
        marker = self.root / 'observer.args'
        observer = tools / 'sp_semantic_observe.py'
        observer.write_text('import pathlib,sys\n'
                            f'pathlib.Path({str(marker)!r}).write_text(" ".join(sys.argv[1:]))\n')
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl(), label='com.ssot.semantic',
                                 root=self.root, extra_env={'SSOT_SEMANTIC_REAP_MANUAL': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        events = [json.loads(x) for x in Path(self.lifecycle).read_text().splitlines()]
        self.assertTrue(any(x.get('event') == 'reaped' and x.get('manual') == 1 for x in events))

    def test_reaper_restores_lease_when_term_fails(self):
        proc = self.start_dummy_socket(ignore_term=True)
        self.write_daemon_state(proc.pid, active=0)
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(Path(self.root / 'want').exists())
        self.assertIsNone(proc.poll())
        self.assertTrue(os.path.exists(self.sock))
        self.assertIn('term_failed', Path(self.lifecycle).read_text())

    def test_reaper_cleans_stale_state(self):
        Path(self.root / 'want').touch()
        Path(self.state).write_text('{}')
        Path(self.sock).touch()
        result = self.run_reaper(self.fake_launchctl(running=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(self.root / 'want').exists())
        self.assertFalse(os.path.exists(self.sock))
        self.assertIn('stale_cleanup', Path(self.lifecycle).read_text())

    def test_reaper_keeps_fresh_lease_when_daemon_not_started(self):
        """冷启动竞态：acquire 已 touch 租约但 launchd 尚未拉起，不得清租约。"""
        Path(self.root / 'want').touch()
        result = self.run_reaper(self.fake_launchctl(running=False),
                                 extra_env={'SSOT_SEMANTIC_LEASE_STALE_SEC': '60'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(Path(self.root / 'want').exists())
        text = Path(self.lifecycle).read_text() if Path(self.lifecycle).exists() else ''
        self.assertNotIn('stale_cleanup', text)

    def test_reaper_reaps_daemon_without_lease(self):
        """无租约但 socket 仍活着（stray/手工拉起的 daemon），必须显式回收。"""
        proc = self.start_dummy_socket()
        self.write_daemon_state(proc.pid, active=0)
        result = self.run_reaper(self.fake_launchctl())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(proc.poll())
        self.assertIn('reaped', Path(self.lifecycle).read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)

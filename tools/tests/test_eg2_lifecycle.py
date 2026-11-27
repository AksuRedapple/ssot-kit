#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
ACQUIRE = TOOLS / 'sp_eg2_acquire.sh'
REAPER = TOOLS / 'sp_eg2_reaper.sh'

SERVER_CODE = r'''
import http.server, os, signal, sys
port=int(sys.argv[1]); pidfile=sys.argv[2]; ignore=sys.argv[3]=='1'
if ignore:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(pidfile,'w').write(str(os.getpid()))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self,*a): pass
http.server.ThreadingHTTPServer(('127.0.0.1',port),H).serve_forever()
'''


class Eg2LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.port = self.free_port()
        self.lease = self.root / 'want'
        self.lifecycle = self.root / 'lifecycle.jsonl'
        self.pidfile = self.root / 'server.pid'
        self.servers = []

    def tearDown(self):
        for p in self.servers:
            if p.poll() is None:
                p.kill(); p.wait(2)
        self.tmp.cleanup()

    @staticmethod
    def free_port():
        s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
        return port

    def start_server(self, ignore_term=False):
        p = subprocess.Popen([sys.executable, '-c', SERVER_CODE, str(self.port), str(self.pidfile),
                              '1' if ignore_term else '0'])
        self.servers.append(p)
        for _ in range(100):
            try:
                s = socket.create_connection(('127.0.0.1', self.port), timeout=.2); s.close(); return p
            except OSError:
                time.sleep(.02)
        self.fail('fake health server not ready')

    def env(self, **extra):
        e = os.environ.copy()
        e.update(SSOT_EG2_PORT=str(self.port), SSOT_EG2_LEASE=str(self.lease),
                 SSOT_EG2_LIFECYCLE_LOG=str(self.lifecycle), SSOT_EG2_IDLE_SEC='0',
                 SSOT_EG2_TERM_WAIT_SEC='1')
        e.update(extra)
        return e

    def run_reaper(self, bindir, label='test.eg2', extra_env=None):
        e = self.env(PATH=bindir + ':' + os.environ.get('PATH', ''), SSOT_EG2_LABEL=label)
        if extra_env:
            e.update(extra_env)
        return subprocess.run(['/bin/bash', str(REAPER)], capture_output=True, text=True, env=e, timeout=15)

    def fake_launchctl(self, running=True):
        bindir = self.root / 'bin'; bindir.mkdir(exist_ok=True)
        state = 'running' if running else 'not running'
        script = bindir / 'launchctl'
        script.write_text(f'''#!/bin/bash
if [ "$1" = print ]; then echo "state = {state}"; exit 0; fi
if [ "$1" = kill ]; then
  pid=$({sys.executable} -c 'import sys; print(open(sys.argv[1]).read().strip())' "{self.pidfile}")
  kill -TERM "$pid"
  exit 0
fi
exit 1
''')
        script.chmod(0o755)
        return str(bindir)

    def old_lease(self):
        self.lease.touch()
        old = time.time() - 100
        os.utime(self.lease, (old, old))

    def test_acquire_cold_and_hot(self):
        def later():
            time.sleep(.4)
            self.start_server()
        import threading
        threading.Thread(target=later, daemon=True).start()
        e = self.env(SSOT_EG2_ACQUIRE_TIMEOUT='3')
        p = subprocess.run(['/bin/bash', str(ACQUIRE)], capture_output=True, text=True, env=e, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.lease.exists())
        text = self.lifecycle.read_text()
        self.assertIn('acquire', text)
        self.assertIn('ready', text)

    def test_reaper_reaps_idle(self):
        proc = self.start_server()
        self.old_lease()
        p = self.run_reaper(self.fake_launchctl())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.lease.exists())
        self.assertIsNotNone(proc.poll())
        self.assertIn('reaped', self.lifecycle.read_text())

    def test_reaper_skips_active_connection(self):
        proc = self.start_server()
        self.old_lease()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        try:
            p = self.run_reaper(self.fake_launchctl())
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(self.lease.exists())
            self.assertIsNone(proc.poll())
        finally:
            s.close()

    def test_reaper_skips_connection_arriving_during_grace(self):
        import threading
        proc = self.start_server()
        self.old_lease()
        result = {}

        def run():
            result['proc'] = self.run_reaper(self.fake_launchctl())

        th = threading.Thread(target=run)
        th.start()
        time.sleep(.3)
        held = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        try:
            th.join(5)
            self.assertEqual(result['proc'].returncode, 0, result['proc'].stderr)
            self.assertTrue(self.lease.exists())
            self.assertIsNone(proc.poll())
            self.assertIn('skip_race', self.lifecycle_text())
        finally:
            held.close()

    def test_reaper_restores_lease_when_term_fails(self):
        proc = self.start_server(ignore_term=True)
        self.old_lease()
        p = self.run_reaper(self.fake_launchctl())
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertTrue(self.lease.exists())
        self.assertIsNone(proc.poll())
        self.assertIn('term_failed', self.lifecycle.read_text())

    def lifecycle_text(self):
        return self.lifecycle.read_text() if self.lifecycle.exists() else ''

    def test_reaper_cleans_stale_lease(self):
        self.old_lease()
        p = self.run_reaper(self.fake_launchctl(running=False),
                            extra_env={'SSOT_EG2_LEASE_STALE_SEC': '60'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.lease.exists())
        self.assertIn('stale_cleanup', self.lifecycle.read_text())

    def test_reaper_keeps_fresh_lease_when_job_not_started(self):
        """冷启动竞态：acquire 已 touch 租约但 launchd 尚未拉起，不得清租约。"""
        self.lease.touch()
        p = self.run_reaper(self.fake_launchctl(running=False),
                            extra_env={'SSOT_EG2_LEASE_STALE_SEC': '60'})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(self.lease.exists())
        self.assertNotIn('stale_cleanup', self.lifecycle_text())

    def test_reaper_reaps_running_without_lease(self):
        """A589 对偶：租约已消失但服务还在跑（测试/手工启动），必须显式回收。"""
        proc = self.start_server()
        p = self.run_reaper(self.fake_launchctl())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNotNone(proc.poll())
        self.assertIn('reaped', self.lifecycle.read_text())

    def test_reaper_no_lease_active_connection_protects(self):
        proc = self.start_server()
        s = socket.create_connection(('127.0.0.1', self.port), timeout=2)
        try:
            p = self.run_reaper(self.fake_launchctl())
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(self.lease.exists())
            self.assertIsNone(proc.poll())
        finally:
            s.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)

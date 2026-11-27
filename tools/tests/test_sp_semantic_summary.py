#!/usr/bin/env python3
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
SCRIPT = TOOLS / 'sp_semantic_summary.py'
sys.path.insert(0, str(TOOLS))
import sp_semantic_observe as OBS  # noqa: E402


class SemanticSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.draft = self.root / 'drafts' / 'semantic-idle-reap'
        (self.root / 'logs').mkdir(parents=True)
        (self.root / 'S2-index').mkdir(parents=True)
        self.draft.mkdir(parents=True)
        self.now = datetime.datetime.now().astimezone()
        (self.draft / 'observation-start.json').write_text(
            json.dumps({'ts': (self.now - datetime.timedelta(days=1)).isoformat()}))

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, event, **kw):
        return {'ts': self.now.isoformat(timespec='seconds'), 'event': event, **kw}

    def query(self, status='ok'):
        return {'ts': self.now.isoformat(timespec='seconds'), 'status': status}

    def run_summary(self):
        out = self.draft / 'summary.md'
        subprocess.check_output([sys.executable, str(SCRIPT), '--root', str(self.root),
                                 '--out', str(out)], text=True, timeout=30)
        return json.loads((self.draft / 'summary.json').read_text())

    def test_high_cold_rate_recommends_45m(self):
        events = []
        for _ in range(10):
            events += [self.event('acquire', mode='cold'),
                       self.event('ready', mode='cold', elapsed_s=3)]
        events.append(self.event('reaped', idle_s=1800))
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(self.query()) + '\n' for _ in range(100)))
        got = self.run_summary()
        self.assertEqual(got['cold_start_rate_pct'], 10.0)
        self.assertIn('45 分钟', got['recommendation'])

    def test_normal_rate_keeps_30m(self):
        events = []
        for _ in range(2):
            events += [self.event('acquire', mode='cold'),
                       self.event('ready', mode='cold', elapsed_s=2)]
        events.append(self.event('reaped', idle_s=1800))
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(self.query()) + '\n' for _ in range(100)))
        got = self.run_summary()
        self.assertEqual(got['cold_start_rate_pct'], 2.0)
        self.assertEqual(got['reap_idle_min_s'], 1800)
        self.assertIn('保持 30 分钟', got['recommendation'])

    def test_fallback_attempt_does_not_double_count_query(self):
        events = [self.event('acquire', mode='cold'),
                  self.event('ready', mode='cold', elapsed_s=2)]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        rows = [self.query('daemon_fallback'), self.query('ok')]
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in rows))
        got = self.run_summary()
        self.assertEqual(got['totals']['queries'], 1)
        self.assertEqual(got['totals']['attempts'], 2)
        self.assertEqual(got['totals']['fallback'], 1)
        self.assertEqual(got['fallback_rate_pct'], 50.0)

    def test_short_reap_idle_blocks_tuning(self):
        events = [self.event('acquire', mode='cold'),
                  self.event('ready', mode='cold', elapsed_s=2),
                  self.event('reaped', idle_s=60)]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(json.dumps(self.query()) + '\n')
        got = self.run_summary()
        self.assertEqual(got['reap_idle_min_s'], 60)
        self.assertIn('回收 idle 异常', got['recommendation'])

    def test_post_fix_window(self):
        fix = self.now - datetime.timedelta(hours=1)
        (self.draft / 'fix-observation.json').write_text(json.dumps({'ts': fix.isoformat()}))
        before = self.now - datetime.timedelta(hours=2)
        after = self.now - datetime.timedelta(minutes=30)
        events = [
            {'ts': before.isoformat(), 'event': 'acquire', 'mode': 'cold'},
            {'ts': before.isoformat(), 'event': 'ready', 'mode': 'cold', 'elapsed_s': 8},
            {'ts': after.isoformat(), 'event': 'acquire', 'mode': 'cold'},
            {'ts': after.isoformat(), 'event': 'ready', 'mode': 'cold', 'elapsed_s': 1},
        ]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        rows = [{'ts': before.isoformat(), 'status': 'daemon_fallback'},
                {'ts': after.isoformat(), 'status': 'ok'}]
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in rows))
        got = self.run_summary()
        self.assertEqual(got['post_fix']['queries'], 1)
        self.assertEqual(got['post_fix']['wake_pct'], 100.0)
        self.assertEqual(got['post_fix']['fallback_pct'], 0.0)
        self.assertFalse(got['post_fix']['sufficient'])
        self.assertIn('样本不足', got['recommendation'])

    def test_post_fix_sufficient_keeps_30m(self):
        fix = self.now - datetime.timedelta(hours=1)
        after = self.now - datetime.timedelta(minutes=30)
        (self.draft / 'fix-observation.json').write_text(json.dumps({'ts': fix.isoformat()}))
        events = [
            {'ts': after.isoformat(), 'event': 'acquire', 'mode': 'cold'},
            {'ts': after.isoformat(), 'event': 'ready', 'mode': 'cold', 'elapsed_s': 1},
            {'ts': after.isoformat(), 'event': 'acquire', 'mode': 'cold'},
            {'ts': after.isoformat(), 'event': 'ready', 'mode': 'cold', 'elapsed_s': 2},
            {'ts': after.isoformat(), 'event': 'reaped', 'idle_s': 1800},
        ]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps({'ts': after.isoformat(), 'status': 'ok'}) + '\n'
                    for _ in range(100)))
        got = self.run_summary()
        self.assertTrue(got['post_fix']['sufficient'])
        self.assertEqual(got['post_fix']['cold_rate_pct'], 2.0)
        self.assertIn('保持 30 分钟', got['recommendation'])

    def test_reap_memory_delta(self):
        before = self.now - datetime.timedelta(minutes=10)
        post = {'trigger': 'reap', 'state': 'missing', 'footprint': '',
                'physmem': 'PhysMem: 15G used (3000M wired, 3900M compressor), 1300M unused.',
                'swap': 'vm.swapusage: total = 8192.00M  used = 6100.00M'}
        rows = [
            {'ts': before.isoformat(), 'trigger': 'manual', 'state': 'running',
             'footprint': 'Physical footprint: 1.1G',
             'physmem': 'PhysMem: 15G used (3000M wired, 5000M compressor), 200M unused.',
             'swap': 'vm.swapusage: total = 8192.00M  used = 7000.00M'},
            {'ts': (self.now - datetime.timedelta(seconds=2)).isoformat(), **post},
            {'ts': (self.now - datetime.timedelta(seconds=1)).isoformat(), **post},
        ]
        (self.draft / 'observations.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in rows))
        got = self.run_summary()
        self.assertEqual(got['avg_reaped_footprint_gib'], 1.1)
        self.assertEqual(len(got['memory_release']), 1)
        delta = got['memory_release'][0]
        self.assertEqual(delta['unused_delta_mib'], 1100.0)
        self.assertEqual(delta['compressor_delta_mib'], -1100.0)
        self.assertEqual(delta['swap_used_delta_mib'], -900.0)

    def test_manual_reap_excluded_from_idle_stats(self):
        manual_ts = self.now.isoformat(timespec='seconds')
        natural_ts = (self.now - datetime.timedelta(minutes=1)).isoformat(timespec='seconds')
        events = [
            self.event('acquire', mode='cold'),
            self.event('ready', mode='cold', elapsed_s=2),
            {'ts': natural_ts, 'event': 'reaped', 'idle_s': 1800},
            {'ts': manual_ts, 'event': 'reaped', 'idle_s': 60},
        ]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        (self.draft / 'manual-reaps.json').write_text(
            json.dumps({'reaps': [{'ts': manual_ts, 'reason': 'test'}]}))
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(self.query()) + '\n' for _ in range(100)))
        got = self.run_summary()
        self.assertEqual(got['reap_idle_min_s'], 1800)
        self.assertEqual(got['manual_reaps_excluded'], 1)
        self.assertNotIn('回收 idle 异常', got['recommendation'])

    def test_observer_window_and_fallback_denominator(self):
        since = self.now - datetime.timedelta(hours=1)
        old = self.now - datetime.timedelta(hours=2)
        recent = self.now - datetime.timedelta(minutes=10)
        stale = self.now - datetime.timedelta(hours=25)
        (self.root / 'logs' / 'semantic-daemon.log').write_text(
            f'{old:%Y-%m-%d %H:%M:%S} query ms=999 top=5 vec=False ok=True\n'
            f'{recent:%Y-%m-%d %H:%M:%S} query ms=100 top=5 vec=False ok=True\n',
            encoding='utf-8')
        rows = [
            {'ts': stale.isoformat(), 'status': 'daemon_fallback'},
            {'ts': old.isoformat(), 'status': 'daemon_fallback'},
            {'ts': recent.isoformat(), 'status': 'daemon_fallback'},
            {'ts': recent.isoformat(), 'status': 'ok'},
        ]
        (self.root / 'S2-index' / 'search-log.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in rows), encoding='utf-8')
        p50, p90, n, fallback, queries, rate = OBS._query_stats(
            str(self.root), since.isoformat())
        self.assertEqual((p50, p90, n), (100, 100, 1))
        self.assertEqual((fallback, queries, rate), (1, 2, 50.0))

    def test_empty_window_is_inconclusive(self):
        got = self.run_summary()
        self.assertIn('证据不足', got['recommendation'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

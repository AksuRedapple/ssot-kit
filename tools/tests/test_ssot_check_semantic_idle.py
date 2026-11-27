#!/usr/bin/env python3
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import ssot_check  # noqa: E402


class SemanticIdleStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'logs').mkdir()
        self.state = self.root / 'state.json'
        self.old = os.environ.get('SSOT_SEMANTIC_STATE')
        os.environ['SSOT_SEMANTIC_STATE'] = str(self.state)
        self.now = datetime.datetime.now().astimezone()

    def tearDown(self):
        if self.old is None:
            os.environ.pop('SSOT_SEMANTIC_STATE', None)
        else:
            os.environ['SSOT_SEMANTIC_STATE'] = self.old
        self.tmp.cleanup()

    def event(self, hours, event, **kw):
        return {'ts': (self.now - datetime.timedelta(hours=hours)).isoformat(timespec='seconds'),
                'event': event, **kw}

    def test_counts_and_state(self):
        events = [self.event(1, 'acquire', mode='cold'), self.event(1, 'ready', mode='cold', elapsed_s=8),
                  self.event(1, 'skip_active'), self.event(2, 'reaped'),
                  self.event(48, 'reaped'), self.event(48, 'ready', mode='hot')]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        self.state.write_text(json.dumps({'active': 1, 'last_query': self.now.timestamp() - 300,
                                          'stopping': False, 'pid': 123}))
        got = ssot_check.semantic_idle_stats(str(self.root))
        self.assertEqual(got['24h']['cold_acquire'], 1)
        self.assertEqual(got['24h']['cold_ready'], 1)
        self.assertEqual(got['24h']['wake_success_pct'], 100.0)
        self.assertEqual(got['24h']['cold_p95_s'], 8)
        self.assertEqual(got['24h']['ready'], 1)
        self.assertEqual(got['24h']['skip_active'], 1)
        self.assertEqual(got['7d']['reaped'], 2)
        self.assertEqual(got['state'], 'active')
        self.assertGreaterEqual(got['idle_min'], 4)

    def test_manual_reap_separate(self):
        manual_ts = (self.now - datetime.timedelta(minutes=5)).isoformat(timespec='seconds')
        natural_ts = (self.now - datetime.timedelta(minutes=10)).isoformat(timespec='seconds')
        events = [{'ts': natural_ts, 'event': 'reaped', 'idle_s': 1800},
                  {'ts': manual_ts, 'event': 'reaped', 'idle_s': 60}]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        d = self.root / 'drafts' / 'semantic-idle-reap'
        d.mkdir(parents=True)
        (d / 'manual-reaps.json').write_text(
            json.dumps({'reaps': [{'ts': manual_ts, 'reason': 'test'}]}))
        got = ssot_check.semantic_idle_stats(str(self.root))
        self.assertEqual(got['24h']['reaped'], 1)
        self.assertEqual(got['24h']['manual_reaped'], 1)

    def test_missing_state(self):
        got = ssot_check.semantic_idle_stats(str(self.root))
        self.assertEqual(got['state'], 'missing')
        self.assertIsNone(got['idle_min'])
        self.assertEqual(got['last'], '')
        self.assertIsNone(got['24h']['wake_success_pct'])
        self.assertIsNone(got['24h']['cold_p95_s'])

    def test_observation_start_filters_commissioning(self):
        start = self.now - datetime.timedelta(hours=1)
        start_dir = self.root / 'drafts' / 'semantic-idle-reap'
        start_dir.mkdir(parents=True)
        (start_dir / 'observation-start.json').write_text(json.dumps({'ts': start.isoformat()}))
        events = [self.event(2, 'acquire', mode='cold'),
                  self.event(.5, 'acquire', mode='cold'),
                  self.event(.5, 'ready', mode='cold', elapsed_s=3)]
        (self.root / 'logs' / 'semantic-lifecycle.jsonl').write_text(
            ''.join(json.dumps(x) + '\n' for x in events))
        got = ssot_check.semantic_idle_stats(str(self.root))
        self.assertEqual(got['24h']['cold_acquire'], 1)
        self.assertEqual(got['24h']['cold_ready'], 1)
        self.assertEqual(got['24h']['wake_success_pct'], 100.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

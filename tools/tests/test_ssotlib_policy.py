#!/usr/bin/env python3
"""回归：ssotlib.policy / fingerprint / pending / index.chunking。

这些是索引线的「非检索」底座：策略决定哪些源进索引、指纹决定 BUILD 记录什么、
pending 决定什么时候跑索引、切块决定块边界。口径漂移会静默改变索引内容。
"""
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import fingerprint, pending, policy  # noqa: E402
from ssotlib.index import chunking  # noqa: E402


class TestPolicy(unittest.TestCase):
    def test_defaults_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = policy.load_policy(td)
            self.assertFalse(p['enabled'])
            self.assertEqual(p['include'], ['human', 'decision', 'unknown'])
            self.assertEqual(p['skip'], ['automation', 'monitor'])
            self.assertEqual(policy.summary(p, 0), 'disabled（全部入索引）')

    def test_enabled_when_file_without_key(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'profile'))
            with open(os.path.join(td, 'profile', 'index-policy.json'), 'w') as f:
                json.dump({'include': ['human'], 'skip': ['monitor']}, f)
            p = policy.load_policy(td)
            self.assertTrue(p['enabled'])
            self.assertEqual(policy.summary(p, 6),
                             'include=human skip=monitor retired=6')

    def test_retired_last_event_wins(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'profile'))
            rows = [{'sid': 'a', 'op': 'retire'}, {'sid': 'b', 'op': 'retire'},
                    {'sid': 'b', 'op': 'unretire'}]
            with open(os.path.join(td, 'profile', 'retired.jsonl'), 'w') as f:
                f.write('\n'.join(json.dumps(r) for r in rows) + '\n坏行\n')
            retired, state = policy.load_retired(td)
            self.assertEqual(retired, {'a'})
            self.assertEqual(state['b']['op'], 'unretire')

    def test_class_and_included(self):
        self.assertEqual(policy.class_of({'session_class': 'Monitor'}), 'monitor')
        self.assertEqual(policy.class_of({'session_class': '怪值'}), 'unknown')
        self.assertEqual(policy.class_of({}), 'human')
        pol = {'enabled': True, 'include': ['human'], 'skip': ['monitor']}
        self.assertFalse(policy.included('monitor', pol))
        self.assertTrue(policy.included('human', pol))
        self.assertTrue(policy.included('monitor', pol, all_classes=True))
        self.assertTrue(policy.included('monitor', pol, only=['monitor']))
        self.assertFalse(policy.included('human', pol, only=['monitor']))

    def test_suggest_class(self):
        pol = {'rules': [{'match': {'title_regex': '巡检'}, 'class': 'monitor',
                          'reason': '标题是巡检'}]}
        cls, reason, src = policy.suggest_class({'title': '每日巡检'}, 'evidence/x', pol)
        self.assertEqual((cls, src), ('monitor', 'rule'))
        cls, _r, src = policy.suggest_class({'session_class': 'decision'}, 'evidence/x', {})
        self.assertEqual((cls, src), ('decision', 'existing'))
        cls, _r, src = policy.suggest_class(
            {'session_class': 'decision', 'class_source': 'manual'}, 'evidence/x', {})
        self.assertEqual((cls, src), ('decision', 'manual'))


class TestFingerprint(unittest.TestCase):
    def test_model_fp_missing_and_readable(self):
        self.assertTrue(fingerprint.model_fp('/nonexistent/m.gguf').startswith('missing:'))
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'abc'); f.flush()
            self.assertEqual(len(fingerprint.model_fp(f.name)), 12)

    def test_env_shape(self):
        e = fingerprint.env('/nonexistent/m.gguf')
        self.assertEqual(set(e), {'hardware_fp', 'model_fp', 'model_path',
                                  'llama_version', 'backend'})
        self.assertTrue(fingerprint.backend().startswith(sys.platform + '-'))


class TestChunking(unittest.TestCase):
    def test_target_and_hard_limit(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False) as f:
            f.write('a' * 120 + '\n' + 'b' * 120 + '\n')
            path = f.name
        try:
            chunks = chunking.chunk_file(path, target=100, hard=150)
            self.assertTrue(all(len(t) <= 150 for _s, t, _r, _t in chunks))
            self.assertGreaterEqual(len(chunks), 2)
            # 硬上限：超长单块被切成多段，行号保留起始
            chunks = chunking.chunk_file(path, target=10000, hard=100)
            self.assertEqual(len(chunks), 3)   # 240 字 → 100+100+40
        finally:
            os.unlink(path)

    def test_empty(self):
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            path = f.name
        try:
            self.assertEqual(chunking.chunk_file(path), [])
        finally:
            os.unlink(path)


class TestSingleTruth(unittest.TestCase):
    def test_shims_and_importers(self):
        import sp_convert
        import sp_coverage
        import sp_embed_bench
        import sp_exit
        import sp_fingerprint
        import sp_index
        import sp_policy
        self.assertIs(sp_policy.summary, policy.summary)
        self.assertIs(sp_policy.load_policy, policy.load_policy)
        self.assertIs(sp_fingerprint.model_fp, fingerprint.model_fp)
        self.assertIs(sp_index.sp_policy, policy)
        self.assertIs(sp_index.sp_pending, pending)
        self.assertIs(sp_index.chunk_file, chunking.chunk_file)
        self.assertIs(sp_coverage.sp_policy, policy)
        self.assertIs(sp_exit.sp_policy, policy)
        self.assertIs(sp_embed_bench.sp_fingerprint, fingerprint)
        self.assertIs(sp_convert.sp_pending, pending)

    def test_sp_pending_cli_is_thin(self):
        with open(os.path.join(TOOLS, 'sp_pending.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('from ssotlib import pending', src)
        self.assertNotIn('def merge(', src)
        self.assertNotIn('flock', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""回归：ssotlib.secrets 的分级与替换（P2 的唯一实现）。

判据：词边界（task-/ask-/hard-disk- 不算）、短 sk- 的上下文分级、
high/medium/low 三档替换、sha256 白名单。
"""
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import secrets as S  # noqa: E402

KEY = 'sk-' + 'a' * 30


class ClassifyTest(unittest.TestCase):
    def kinds(self, text):
        return [(f['kind'], f['confidence']) for f in S.classify(text)]

    def test_high_patterns(self):
        self.assertEqual(self.kinds(KEY), [('sk_full', 'high')])
        self.assertEqual(self.kinds('ghp_' + 'b' * 40), [('ghp', 'high')])
        self.assertEqual(self.kinds('github_pat_' + 'c' * 40), [('github_pat', 'high')])
        self.assertEqual(self.kinds('AKIA' + 'D' * 16), [('akia', 'high')])
        self.assertEqual(self.kinds('hf_' + 'e' * 40), [('hf', 'high')])
        pem = '-----BEGIN ' + 'RSA ' + 'PRIVATE KEY-----'
        self.assertEqual(self.kinds(pem), [('pem', 'high')])

    def test_short_sk_confidence(self):
        self.assertEqual(self.kinds('api_key: sk-deadbeef'), [('sk_short', 'medium')])
        self.assertEqual(self.kinds('随便写的 sk-deadbeef'), [('sk_short', 'low')])

    def test_bearer_is_medium(self):
        self.assertEqual(self.kinds('Authorization: Bearer ' + 'f' * 40),
                         [('bearer', 'medium')])
        self.assertEqual(self.kinds('Bearer ' + 'f' * 10), [])   # 太短

    def test_word_boundaries(self):
        for t in ('task-deadbeef', 'ask-at-poorest', 'hard-disk-4f2a',
                  'risk-assessment', 'disk-cafe1234'):
            self.assertEqual(S.classify(t), [], t)

    def test_overlap_longest_wins(self):
        ms = S.classify('Bearer ' + KEY)
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0]['kind'], 'bearer')

    def test_hash8_and_counts(self):
        self.assertEqual(len(S.hash8(KEY)), 8)
        self.assertEqual(S.counts(f'{KEY} api_key: sk-deadbeef'), 
                         {'high': 1, 'medium': 1, 'low': 0})


class ScrubTest(unittest.TestCase):
    def test_levels(self):
        text = f'{KEY} Bearer ' + 'g' * 40 + ' sk-deadbeef'
        self.assertNotIn(KEY, S.scrub(text, level='high'))
        self.assertIn('Bearer', S.scrub(text, level='high'))
        self.assertNotIn('Bearer', S.scrub(text, level='medium'))
        self.assertNotIn('sk-deadbeef', S.scrub(text, level='medium'))
        low = '随便写的 sk-deadbeef'
        self.assertIn('sk-deadbeef', S.scrub(low, level='medium'))
        self.assertNotIn('sk-deadbeef', S.scrub(low, level='all'))

    def test_allowlist(self):
        h = S.hash8(KEY)
        out = S.scrub(f'x {KEY}', level='high', allowlist={h})
        self.assertIn(KEY, out)
        out = S.scrub(f'x {KEY}', level='high', allowlist={'00000000'})
        self.assertNotIn(KEY, out)

    def test_non_string_and_empty(self):
        self.assertEqual(S.scrub(''), '')
        self.assertEqual(S.scrub(None), '')


class BackwardCompatTest(unittest.TestCase):
    def test_secret_rx_shape(self):
        self.assertTrue(S.SECRET_RX)
        self.assertTrue(all(hasattr(rx, 'findall') for rx, _ in S.SECRET_RX))
        # 旧正则会把 task- 词尾当 key；新 SECRET_RX 不应如此
        self.assertEqual(sum(len(rx.findall('task-deadbeef')) for rx, _ in S.SECRET_RX), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

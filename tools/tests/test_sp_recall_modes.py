#!/usr/bin/env python3
"""回归：sp_recall 的三种查询模式（and 默认 / phrase / regex）。

2026-11-23（批次 5 P3）：旧实现把 pattern 当整串正则，用户输入
"Docker.raw 稀疏文件" 时要求两个词连续出现，召回骤降。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_recall as R  # noqa: E402


class MatcherTest(unittest.TestCase):
    def test_and_order_independent(self):
        m, mode = R.make_matcher('Docker.raw 稀疏文件')
        self.assertEqual(mode, 'and')
        self.assertIsNotNone(m.search('先看 稀疏文件 再说 Docker.raw'))
        self.assertIsNone(m.search('只有 Docker.raw'))
        self.assertIsNone(m.search('只有 稀疏文件'))

    def test_and_is_literal_not_regex(self):
        m, _ = R.make_matcher('Docker.raw')
        self.assertIsNotNone(m.search('Docker.raw'))
        self.assertIsNone(m.search('DockerXraw'))

    def test_phrase_requires_contiguous(self):
        m, mode = R.make_matcher('Docker.raw 稀疏文件', mode='phrase')
        self.assertEqual(mode, 'phrase')
        self.assertIsNotNone(m.search('Docker.raw 稀疏文件'))
        self.assertIsNone(m.search('稀疏文件 Docker.raw'))

    def test_regex_explicit(self):
        m, mode = R.make_matcher(r'Docker\.raw', mode='regex')
        self.assertEqual(mode, 'regex')
        self.assertIsNotNone(m.search('Docker.raw'))
        self.assertIsNone(m.search('DockerXraw'))

    def test_ignore_case(self):
        m, _ = R.make_matcher('docker.raw', ignore_case=True)
        self.assertIsNotNone(m.search('DOCKER.RAW'))

    def test_empty_pattern(self):
        with self.assertRaises(ValueError):
            R.make_matcher('   ')


class CliTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.old = (R.SSOT, sys.argv)
        R.SSOT = self._td.name
        d = Path(self._td.name) / 'evidence/cc/S1-sessions/2026-11-22-deadbeef-x'
        d.mkdir(parents=True)
        rows = [
            {'t': '2026-11-22T01:00:00Z', 'role': 'user', 'kind': 'text',
             'content': '先看 稀疏文件 再说 Docker.raw 的情况'},
            {'t': '2026-11-22T01:00:01Z', 'role': 'assistant', 'kind': 'text',
             'content': 'Docker.raw 稀疏文件 连续出现'},
            {'t': '2026-11-22T01:00:02Z', 'role': 'assistant', 'kind': 'text',
             'content': '只有 DockerXraw'},
        ]
        with open(d / 'transcript.jsonl', 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def tearDown(self):
        R.SSOT, sys.argv = self.old
        self._td.cleanup()

    def run_cli(self, *argv):
        sys.argv = ['sp_recall.py', *argv]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = R.main() or 0
        return code, buf.getvalue()

    def test_default_and_finds_both(self):
        code, out = self.run_cli('Docker.raw 稀疏文件', '--json')
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d['mode'], 'and')
        self.assertEqual(d['count'], 2)          # 两条都含两个词
        self.assertTrue(all('DockerXraw' not in h['snippet'] for h in d['hits']))

    def test_phrase_and_regex(self):
        code, out = self.run_cli('Docker.raw 稀疏文件', '--phrase', '--json')
        self.assertEqual(json.loads(out)['count'], 1)
        code, out = self.run_cli(r'Docker\.raw', '--mode', 'regex', '--json')
        d = json.loads(out)
        self.assertEqual(d['mode'], 'regex')
        self.assertEqual(d['count'], 2)

    def test_text_output_labels_mode(self):
        code, out = self.run_cli('Docker.raw 稀疏文件')
        self.assertIn('模式 and', out)

    def test_unknown_harness(self):
        code, out = self.run_cli('x', '--harness', 'nope')
        self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

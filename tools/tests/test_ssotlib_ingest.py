#!/usr/bin/env python3
"""回归：ssotlib.ingest（脱敏 / 内容归一 / 时区 / 丢弃类型）。

这些口径直接从 `sp_convert` 搬出，却被归档、巡检、子 agent 派生共用；
脱敏漏一种形态就是把密钥写进 S0/S1。
"""
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import ingest  # noqa: E402


class TestScrub(unittest.TestCase):
    def test_secret_shapes(self):
        cases = [
            'sk-' + 'a' * 24,
            'sk-' + '1234567890abcdef',
            'ghp_' + 'a' * 32,
            'github_pat_' + 'b' * 32,
            'AKIA' + 'C' * 16,
            'hf_' + 'd' * 32,
            'Authorization: Bearer ' + 'e' * 32,
        ]
        for c in cases:
            out = ingest.scrub(c)
            self.assertIn('[REDACTED-SECRET]', out, c)
            self.assertNotIn(c[-12:], out)

    def test_plain_text_untouched(self):
        s = '普通文本：索引重建、A560、~/ssot/tools'
        self.assertEqual(ingest.scrub(s), s)


class TestNormContent(unittest.TestCase):
    def test_string(self):
        self.assertEqual(ingest.norm_content(' hi '), ('text', ' hi '))
        self.assertEqual(ingest.norm_content('   '), ('empty', ''))

    def test_blocks(self):
        kind, payload = ingest.norm_content([
            {'type': 'text', 'text': '第一段'},
            {'type': 'text', 'text': '第二段'},
        ])
        self.assertEqual((kind, payload), ('text', '第一段\n第二段'))

        kind, payload = ingest.norm_content([
            {'type': 'tool_use', 'name': 'Bash', 'input': {'cmd': 'ls'}},
        ])
        self.assertEqual(kind, 'tool_use')
        self.assertEqual(payload[0]['name'], 'Bash')
        self.assertIn('ls', payload[0]['brief'])

        kind, payload = ingest.norm_content([
            {'type': 'tool_result', 'content': [{'text': 'out'}]},
        ])
        self.assertEqual((kind, payload), ('tool_result', ['out']))

    def test_priority_text_over_tool(self):
        kind, _ = ingest.norm_content([
            {'type': 'tool_use', 'name': 'x', 'input': {}},
            {'type': 'text', 'text': '正文'},
        ])
        self.assertEqual(kind, 'text')

    def test_empty(self):
        self.assertEqual(ingest.norm_content(None), ('empty', ''))
        self.assertEqual(ingest.norm_content([]), ('empty', ''))


class TestLocal(unittest.TestCase):
    def test_utc_to_plus8(self):
        d = ingest.local('2026-01-01T00:00:00Z')
        self.assertEqual((d.hour, d.day), (8, 1))
        d = ingest.local('2026-01-01T16:00:00Z')
        self.assertEqual((d.hour, d.day), (0, 2))

    def test_bad(self):
        self.assertIsNone(ingest.local('not-a-time'))
        self.assertIsNone(ingest.local(None))


class TestDropTypes(unittest.TestCase):
    def test_known(self):
        for k in ('attachment', 'runtime-config', 'last-prompt'):
            self.assertIn(k, ingest.DROP_TYPES)


class TestSingleTruth(unittest.TestCase):
    def test_consumers(self):
        import sp_archive
        import sp_convert
        import sp_s0scan
        if not os.path.exists(os.path.join(TOOLS, 'sp_subagent.py')):
            self.skipTest('sp_subagent.py 只在私有实例')
        import sp_subagent
        self.assertIs(sp_convert.scrub, ingest.scrub)
        self.assertIs(sp_convert.SECRET_RX, ingest.SECRET_RX)
        self.assertIs(sp_convert.norm_content, ingest.norm_content)
        self.assertIs(sp_convert.local, ingest.local)
        self.assertIs(sp_archive.SECRET_RX, ingest.SECRET_RX)
        self.assertIs(sp_archive.scrub_text, ingest.scrub)
        self.assertIs(sp_s0scan.SECRET_RX, ingest.SECRET_RX)
        self.assertIs(sp_subagent.norm_content, ingest.norm_content)


if __name__ == '__main__':
    unittest.main(verbosity=2)

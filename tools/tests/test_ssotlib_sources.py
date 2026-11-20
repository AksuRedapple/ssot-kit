#!/usr/bin/env python3
"""回归：ssotlib.sources / session_io。

session_io 的口径事故（2026-11-10）：三个工具各自内联 CC 解析 → 跨 harness 空集，
还把 task-notification 当用户消息（条数虚高 28%）。这里把三种形状与过滤钉死。
"""
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import session_io, sources  # noqa: E402


def write_jsonl(rows):
    f = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False, encoding='utf-8')
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
    f.close()
    return f.name


class TestSessionShapes(unittest.TestCase):
    def tearDown(self):
        if getattr(self, 'path', None):
            os.unlink(self.path)

    def test_cc_and_sidechain(self):
        self.path = write_jsonl([
            {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '真人提问'}]},
             'timestamp': '2026-01-01T10:00:00Z'},
            {'type': 'user', 'isSidechain': True,
             'message': {'content': [{'type': 'text', 'text': '侧链不该算'}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '回答'}]}},
        ])
        msgs = list(session_io.iter_messages(self.path))
        self.assertEqual([m['text'] for m in msgs], ['真人提问', '回答'])
        self.assertEqual([m['shape'] for m in msgs], ['cc', 'cc'])
        self.assertEqual(msgs[0]['ts'], '2026-01-01 10:00:00')

    def test_codex_shape(self):
        self.path = write_jsonl([
            {'type': 'response_item',
             'payload': {'type': 'message', 'role': 'user',
                         'content': [{'type': 'input_text', 'text': 'codex 提问'}]},
             'timestamp': '2026-01-01T10:00:00Z'},
            {'type': 'response_item', 'payload': {'type': 'function_call'}},
        ])
        msgs = list(session_io.iter_messages(self.path))
        self.assertEqual([(m['text'], m['shape'], m['role']) for m in msgs],
                         [('codex 提问', 'codex', 'user')])

    def test_s1_shape(self):
        self.path = write_jsonl([
            {'t': '2026-01-01T10:00:00Z', 'role': 'user', 'kind': 'text', 'content': 'S1 提问'},
            {'role': 'user', 'kind': 'text', 'content': '没有时间也算'},
        ])
        msgs = list(session_io.iter_messages(self.path))
        self.assertEqual([m['text'] for m in msgs], ['S1 提问', '没有时间也算'])
        self.assertTrue(all(m['shape'] == 's1' for m in msgs))

    def test_system_injected_and_tool_result(self):
        self.path = write_jsonl([
            {'type': 'user', 'message': {'content': [
                {'type': 'text', 'text': '<system-reminder>环境注入</system-reminder>'}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'content': 'x'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '真实问题'}]}},
        ])
        human = list(session_io.user_messages(self.path))
        self.assertEqual([m['text'] for m in human], ['真实问题'])
        all_msgs = list(session_io.user_messages(self.path, include_system=True))
        self.assertEqual(len(all_msgs), 2)          # 注入保留，tool_result 仍丢
        self.assertFalse(all_msgs[0]['human'])

    def test_stats(self):
        self.path = write_jsonl([
            {'role': 'user', 'kind': 'text', 'content': '一'},
            {'role': 'user', 'kind': 'text', 'content': '<system-reminder>x</system-reminder>'},
            {'role': 'assistant', 'kind': 'text', 'content': '回答'},
        ])
        self.assertEqual(session_io.stats(self.path), (1, 1, 's1', 1))

    def test_empty(self):
        self.path = write_jsonl([])
        self.assertEqual(session_io.stats(self.path), (0, 0, None, 0))
        self.assertEqual(list(session_io.iter_messages(self.path)), [])


class TestSources(unittest.TestCase):
    def test_parse_since(self):
        self.assertIsNone(sources.parse_since(None))
        self.assertGreater(sources.parse_since('30d'), 0)
        self.assertLess(sources.parse_since('30d'), sources.parse_since('2d'))

    def test_discover_shape(self):
        # 宿主有没有 harness 数据都成立：只验返回形状
        rows = sources.discover()
        self.assertIsInstance(rows, list)
        for r in rows:
            self.assertTrue(set(r) >= {'src', 'role', 'kind', 'sessions', 'files', 'bytes'})
            self.assertIsInstance(r['roots'], list)

    def test_discover_with_temp_root(self):
        # 用临时目录喂 ROOTS，不依赖本机 harness
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'proj'))
            with open(os.path.join(td, 'proj', 'a.jsonl'), 'w', encoding='utf-8') as f:
                f.write('{}\n')
            old = sources.ROOTS
            sources.ROOTS = [('qoder', 'human', 'jsonl', [(td, 'evidence/qoder/S0')])]
            try:
                rows = sources.discover({'qoder'})
            finally:
                sources.ROOTS = old
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['src'], 'qoder')
        self.assertEqual(r['files'], 1)
        self.assertGreaterEqual(r['bytes'], 1)
        self.assertEqual(r['roots'][0]['dest'], 'evidence/qoder/S0')

    def test_single_truth(self):
        import sp_archive
        import sp_recall
        import sp_sources
        self.assertIs(sp_sources.discover, sources.discover)
        self.assertIs(sp_archive.sp_sources, sources)
        self.assertIs(sp_recall.sp_sources, sources)


class TestSingleTruthSessionIo(unittest.TestCase):
    def test_shim(self):
        if not os.path.exists(os.path.join(TOOLS, 'sp_line_split.py')):
            self.skipTest('sp_line_split.py 只在私有实例')
        import sp_line_split
        import sp_session_io
        self.assertIs(sp_session_io.iter_messages, session_io.iter_messages)
        self.assertIs(sp_line_split.session_io, session_io)


if __name__ == '__main__':
    unittest.main(verbosity=2)

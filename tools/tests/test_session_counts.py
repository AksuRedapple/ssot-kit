#!/usr/bin/env python3
"""回归：session_io 的人类消息计数（C5 的口径）。

2026-11-22 事故：S1 把工具结果写成 `role=user, kind=tool_result`，iter_messages
没有看 `kind`，于是 CC 会话 15 条人类消息被数成 630 条；同时本机 harness 的注入
（paseo-system / ssot-context / 时间戳）也没进 SYSTEM_MARKERS，条数再虚高一截。
后果：转生件覆盖率（C5）失去意义。
"""
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import session_io  # noqa: E402


def write_jsonl(tmp, rows, name='t.jsonl'):
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return p


class TestS1Shape(unittest.TestCase):
    def test_tool_result_and_meta_not_human(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_jsonl(td, [
                {'t': '2026-11-22T01:00:00Z', 'role': 'user', 'kind': 'text',
                 'content': '真实问题'},
                {'t': '2026-11-22T01:00:01Z', 'role': 'user', 'kind': 'tool_result',
                 'content': '命令输出' * 100},
                {'t': '2026-11-22T01:00:02Z', 'role': 'user', 'kind': 'meta',
                 'content': '元信息'},
                {'t': '2026-11-22T01:00:03Z', 'role': 'assistant', 'kind': 'text',
                 'content': '回答'},
            ])
            human, injected, shape, _ = session_io.stats(p)
            self.assertEqual(shape, 's1')
            self.assertEqual(human, 1)
            self.assertEqual(injected, 0)

    def test_local_injections_are_not_human(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_jsonl(td, [
                {'role': 'user', 'kind': 'text', 'content': '[ssot-context] 开机记忆'},
                {'role': 'user', 'kind': 'text', 'content': '[SSOT 提醒] 先查再判'},
                {'role': 'user', 'kind': 'text', 'content': '[paseo-warmer] Reply with exactly OK.'},
                {'role': 'user', 'kind': 'text',
                 'content': 'Time sampled while preparing turn 1, step 1: 2026-11-22T01:00'},
                {'role': 'user', 'kind': 'text',
                 'content': 'Base directory for this skill: /opt/example/skills/y'},
                {'role': 'user', 'kind': 'text', 'content': '<paseo-system>派单</paseo-system>'},
                {'role': 'user', 'kind': 'text', 'content': '人类说的话'},
            ])
            human, injected, _, longest = session_io.stats(p)
            self.assertEqual((human, injected), (1, 6))
            self.assertEqual(longest, len('人类说的话'))


class TestCCShape(unittest.TestCase):
    def test_tool_result_blocks_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_jsonl(td, [
                {'type': 'user', 'timestamp': '2026-11-22T01:00:00Z',
                 'message': {'role': 'user', 'content': [{'type': 'text', 'text': '问题'}]}},
                {'type': 'user', 'timestamp': '2026-11-22T01:00:01Z',
                 'message': {'role': 'user',
                             'content': [{'type': 'tool_result', 'content': '输出'}]}},
                {'type': 'user', 'timestamp': '2026-11-22T01:00:02Z', 'isSidechain': True,
                 'message': {'role': 'user', 'content': '子 agent 的消息'}},
                {'type': 'assistant', 'timestamp': '2026-11-22T01:00:03Z',
                 'message': {'role': 'assistant',
                             'content': [{'type': 'text', 'text': '回答'}]}},
            ])
            human, injected, shape, _ = session_io.stats(p)
            self.assertEqual(shape, 'cc')
            self.assertEqual((human, injected), (1, 0))

    def test_codex_rollout_shape(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_jsonl(td, [
                {'type': 'response_item', 'timestamp': '2026-11-22T01:00:00Z',
                 'payload': {'type': 'message', 'role': 'user',
                             'content': [{'type': 'input_text', 'text': '问题'}]}},
                {'type': 'response_item', 'timestamp': '2026-11-22T01:00:01Z',
                 'payload': {'type': 'message', 'role': 'assistant',
                             'content': [{'type': 'output_text', 'text': '回答'}]}},
            ])
            human, injected, shape, _ = session_io.stats(p)
            self.assertEqual(shape, 'codex')
            self.assertEqual(human, 1)

    def test_empty_and_garbage(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_jsonl(td, [{'foo': 'bar'}, {'type': 'summary'}])
            self.assertEqual(session_io.stats(p), (0, 0, None, 0))
            empty = os.path.join(td, 'empty.jsonl')
            open(empty, 'w').close()
            self.assertEqual(session_io.stats(empty), (0, 0, None, 0))


if __name__ == '__main__':
    unittest.main(verbosity=2)

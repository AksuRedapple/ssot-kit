#!/usr/bin/env python3
"""回归：ssotlib.store 的原子写与坏行计数（不静默吞数据）。"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import store  # noqa: E402


class TestReadJson(unittest.TestCase):
    def test_missing_and_bad(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'x.json')
            self.assertEqual(store.read_json(p, {}), {})
            self.assertIsNone(store.read_json(p))
            with open(p, 'w', encoding='utf-8') as f:
                f.write('{坏 JSON')
            self.assertEqual(store.read_json(p, {'d': 1}), {'d': 1})


class TestJsonl(unittest.TestCase):
    def test_bad_lines_counted(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'x.jsonl')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('{"a": 1}\n\nnot-json\n{"a": 2}\n')
            r = store.read_jsonl(p)
            self.assertEqual(len(r['rows']), 2)
            self.assertEqual(r['bad'], 1)
            rows, bad = r                      # 解包兼容
            self.assertEqual((len(rows), bad), (2, 1))

    def test_missing_file(self):
        rows, bad = store.read_jsonl('/nonexistent/x.jsonl')
        self.assertEqual((rows, bad), ([], 0))

    def test_iter_jsonl_keeps_lineno(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'x.jsonl')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('{"a": 1}\nbad\n{"a": 2}\n')
            got = [(n, o is None) for n, o in store.iter_jsonl(p)]
            self.assertEqual(got, [(1, False), (2, True), (3, False)])


class TestAtomicWrite(unittest.TestCase):
    def test_json_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'sub', 'x.json')
            store.write_json_atomic(p, {'标题': '中文', 'n': 1})
            self.assertEqual(store.read_json(p), {'标题': '中文', 'n': 1})
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            # 不留临时文件
            self.assertEqual([f for f in os.listdir(os.path.dirname(p)) if f.endswith('.tmp')], [])
            # 覆盖写
            store.write_json_atomic(p, {'n': 2})
            self.assertEqual(store.read_json(p)['n'], 2)

    def test_jsonl_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'x.jsonl')
            store.write_jsonl_atomic(p, [{'i': 1}, {'i': 2, 's': '中文'}])
            rows, bad = store.read_jsonl(p)
            self.assertEqual(bad, 0)
            self.assertEqual(rows[1]['s'], '中文')
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    def test_failed_write_leaves_original(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'x.json')
            store.write_json_atomic(p, {'ok': True})
            with self.assertRaises(TypeError):
                store.write_json_atomic(p, {'bad': object()})   # 不可序列化
            self.assertEqual(store.read_json(p), {'ok': True})
            self.assertEqual([f for f in os.listdir(td) if f.endswith('.tmp')], [])

    def test_append_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'logs', 'x.jsonl')
            store.append_jsonl(p, {'i': 1})
            store.append_jsonl(p, {'i': 2})
            rows, bad = store.read_jsonl(p)
            self.assertEqual((len(rows), bad), (2, 0))
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)


if __name__ == '__main__':
    unittest.main(verbosity=2)

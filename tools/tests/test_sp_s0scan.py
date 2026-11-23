#!/usr/bin/env python3
"""回归：sp_s0scan 的分级与 --unique（P2）。

判据：high/medium/low 分开计数；low 的 task-/ask- 词尾不再被当密钥；
--unique 按值 sha256 聚合（不打印明文）。
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

import sp_s0scan as S  # noqa: E402

KEY = 'sk-' + 'a' * 30


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.old = (S.SSOT, S.STATE, sys.argv)
        S.SSOT = str(self.root)
        S.STATE = str(self.root / 'alerts/s0-scan.json')
        self.s0 = self.root / 'evidence/cc/S0-archive/claude-projects/p'
        self.s0.mkdir(parents=True)

    def tearDown(self):
        S.SSOT, S.STATE, sys.argv = self.old
        self._td.cleanup()

    def write(self, name, text):
        (self.s0 / name).write_text(text, encoding='utf-8')

    def run_main(self, *argv):
        sys.argv = ['sp_s0scan.py', *argv]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = S.main() or 0
        return code, buf.getvalue()


class ScanTest(Base):
    def test_confidence_split_and_low_ignored(self):
        self.write('a.jsonl', '{"k": "%s"}\n' % KEY)
        self.write('b.jsonl', 'api_key: sk-deadbeef\n')
        self.write('c.jsonl', 'task-deadbeef ask-at-poorest hard-disk-4f2a\n')
        self.write('d.jsonl', 'Authorization: Bearer ' + 'b' * 40 + '\n')
        d = S.scan()
        self.assertEqual(d['files_hit'], 3)      # c 无命中
        self.assertEqual(d['by_confidence']['high'], 1)
        self.assertEqual(d['by_confidence']['medium'], 2)
        self.assertEqual(d['by_confidence']['low'], 0)
        self.assertEqual(d['high_files'], 1)

    def test_unique_aggregation(self):
        self.write('a.jsonl', '{"k": "%s"}\n{"k": "%s"}\n' % (KEY, KEY))
        self.write('b.jsonl', '{"k": "%s"}\n' % KEY)
        d = S.scan(unique=True)
        self.assertEqual(d['unique_count'], 1)
        rec = d['unique'][0]
        self.assertEqual(rec['count'], 3)
        self.assertEqual(rec['files'], 2)
        self.assertEqual(rec['confidence'], 'high')
        self.assertEqual(len(rec['hash']), 8)
        self.assertNotIn(KEY, json.dumps(d, ensure_ascii=False))

    def test_main_json_unique_and_state(self):
        self.write('a.jsonl', '{"k": "%s"}\n' % KEY)
        code, out = self.run_main('--json', '--unique', '--write-state')
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d['unique_count'], 1)
        self.assertTrue(Path(S.STATE).exists())
        st = json.loads(Path(S.STATE).read_text(encoding='utf-8'))
        self.assertEqual(st['by_confidence']['high'], 1)

    def test_only_filter_and_table_output(self):
        self.write('a.jsonl', KEY)
        code, out = self.run_main('--unique')
        self.assertIn('high 1', out)
        self.assertIn('唯一值 1', out)
        code, out = self.run_main('--only', 'qoder')
        self.assertIn('0/0', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""回归：sp_purify 只追加不重写；ssot_check 只认条目行（A558）。"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
import ssot_check  # noqa: E402


class TestPurify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, 'inbox'))
        self.f = os.path.join(self.tmp, 'inbox', '2026-01-01.md')
        with open(self.f, 'w', encoding='utf-8') as f:
            f.write("- 2026-01-01 [fact] 未标记 | source: a\n"
                    "- 2026-01-01 [fact] 已标记 | source: b → 归位: lines/old.md\n"
                    "- 非条目要点：xxx\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_is_entry(self):
        self.assertTrue(ssot_check.is_entry("- 2026-01-01 [fact] x"))
        self.assertTrue(ssot_check.is_entry("- [fact] x"))
        self.assertFalse(ssot_check.is_entry("- 非条目要点：x"))
        self.assertFalse(ssot_check.is_entry("- 取件根：x"))

    def test_marker_count(self):
        self.assertEqual(ssot_check.marker_count(self.tmp), 1)
        self.assertIsNone(ssot_check.head_marker_count(self.tmp))

    def test_dry_run_no_write(self):
        before = open(self.f, encoding='utf-8').read()
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'sp_purify.py'), '--root', self.tmp],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(self.f, encoding='utf-8').read(), before)
        self.assertIn('dry-run', r.stdout)

    def test_apply_only_unmarked_and_backup(self):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'sp_purify.py'), '--root', self.tmp, '--apply'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = open(self.f, encoding='utf-8').read().splitlines()
        self.assertIn('→ 归位:', lines[0])          # 未标记 → 追加
        self.assertIn('lines/old.md', lines[1])     # 已标记 → 原样
        self.assertNotIn('→', lines[2])             # 非条目 → 不动
        bdir = os.path.join(self.tmp, 'backups')
        self.assertTrue(os.path.isdir(bdir) and os.listdir(bdir), 'apply 必须先备份')
        self.assertIn('标记数', r.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)

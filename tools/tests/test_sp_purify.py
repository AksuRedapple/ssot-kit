#!/usr/bin/env python3
"""回归：sp_purify 的护栏（A558 事故的正面）。

判据：默认只补未标记行；已有标记不动；--remap 才重算；--apply 先备份；
写完标记数只增不减。
"""
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_purify  # noqa: E402


class PurifyTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = self._td.name
        os.makedirs(os.path.join(self.root, 'inbox'))
        self.f = os.path.join(self.root, 'inbox', '2026-11-22.md')
        with open(self.f, 'w', encoding='utf-8') as fh:
            fh.write('- 2026-11-22 [fact] SSOT 索引坏了要重跑 | source: x\n')
            fh.write('- 2026-11-22 [fact] 已有标记 | source: y → 归位: lines/ssot-hub.md\n')
            fh.write('- 2026-11-22 [fact] 标记写错了 | source: z → 归位: lines/wrong.md\n')
            fh.write('不是条目行\n')
        self.old_argv = sys.argv

    def tearDown(self):
        sys.argv = self.old_argv
        self._td.cleanup()

    def read(self):
        return open(self.f, encoding='utf-8').read()

    def test_dry_run_plans_only_unmarked(self):
        sys.argv = ['sp_purify.py', '--root', self.root]
        self.assertEqual(sp_purify.main(), 0)
        self.assertNotIn('归位', self.read().splitlines()[0])   # 没写盘
        # 计划里不应包含「已有标记」行
        # （dry-run 只打印，靠写盘结果反证）

    def test_apply_appends_and_keeps_existing(self):
        before = self.read()
        sys.argv = ['sp_purify.py', '--root', self.root, '--apply']
        self.assertEqual(sp_purify.main(), 0)
        after = self.read()
        lines = after.splitlines()
        self.assertIn('归位: lines/ssot-hub.md', lines[1])        # 原标记原样
        self.assertIn('归位: lines/wrong.md', lines[2])           # 错标记也不动
        self.assertIn('→ 归位: lines/ssot-hub.md', lines[0])      # 未标记补上
        self.assertEqual(lines[3], '不是条目行')
        self.assertGreaterEqual(after.count('→'), before.count('→'))
        backups = os.path.join(self.root, 'backups')
        self.assertTrue(os.path.isdir(backups) and os.listdir(backups))

    def test_remap_can_fix_wrong_marker(self):
        sys.argv = ['sp_purify.py', '--root', self.root, '--remap', '--apply']
        self.assertEqual(sp_purify.main(), 0)
        lines = self.read().splitlines()
        # 未命中规则的行走兜底线；关键是错的标记被重算（不再指向 wrong.md）
        self.assertNotIn('lines/wrong.md', self.read())
        self.assertIn('归位: lines/mac-foundation.md', lines[2])

    def test_no_backup_flag(self):
        sys.argv = ['sp_purify.py', '--root', self.root, '--apply', '--no-backup']
        sp_purify.main()
        self.assertFalse(os.path.exists(os.path.join(self.root, 'backups')))

    def test_dest_rules(self):
        self.assertEqual(sp_purify.dest('今天调 algo 判题器', 'x.md'), 'lines/algorithm-training.md')
        self.assertIn('allinone-app', sp_purify.dest('HomeHub 发版 1.0.22', 'x.md'))
        self.assertIn('mac-foundation', sp_purify.dest('launchd 服务挂了', 'x.md'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""回归：ssotlib.entries 是条目/标记/conf 的唯一实现（A558）。

守卫点：
  - ENTRY_RE / is_entry 只有一份：ssot_check、sp_purify 必须引用同一对象
  - 标记计数只认条目行；README 与非条目不算
  - HEAD 对账在无 git 时返回 None（不误报回退）
  - conf 归一化保持四前缀语义
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import entries  # noqa: E402


class TestSingleTruth(unittest.TestCase):
    def test_tools_share_one_entry_re(self):
        import ssot_check
        import sp_purify
        self.assertIs(ssot_check.ENTRY_RE, entries.ENTRY_RE, 'ssot_check 又复制了 ENTRY_RE')
        self.assertIs(sp_purify.ENTRY_RE, entries.ENTRY_RE, 'sp_purify 又复制了 ENTRY_RE')
        self.assertIs(ssot_check.is_entry, entries.is_entry)
        self.assertIs(ssot_check.normalize_conf, entries.normalize_conf)


class TestEntryParsing(unittest.TestCase):
    def test_is_entry(self):
        self.assertTrue(entries.is_entry('- 2026-01-01 [fact] x'))
        self.assertTrue(entries.is_entry('- [fact] x'))
        self.assertTrue(entries.is_entry('- [state] 无日期'))
        self.assertFalse(entries.is_entry('- 非条目要点：x'))
        self.assertFalse(entries.is_entry('- 取件根：x'))
        self.assertFalse(entries.is_entry('  - [fact] 缩进不算'))
        self.assertFalse(entries.is_entry(''))

    def test_has_marker(self):
        self.assertTrue(entries.has_marker('- [fact] x → 归位: lines/a.md'))
        self.assertFalse(entries.has_marker('- [fact] x'))
        # 非条目行里的箭头不算标记
        self.assertFalse(entries.has_marker('- 说明 → 这不是条目'))
        self.assertFalse(entries.has_marker('  - [fact] x → 归位: lines/a.md'))


class TestCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, 'inbox'))
        with open(os.path.join(self.tmp, 'inbox', '2026-01-01.md'), 'w', encoding='utf-8') as f:
            f.write('- 2026-01-01 [fact] 未标记 | source: a | conf: 实测\n'
                    '- 2026-01-01 [fact] 已标记 | source: b → 归位: lines/old.md\n'
                    '- 非条目要点：xxx\n')
        with open(os.path.join(self.tmp, 'inbox', 'README.md'), 'w', encoding='utf-8') as f:
            f.write('- [fact] README 里的示例 → 归位: lines/x.md\n')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_marker_and_pending(self):
        self.assertEqual(entries.marker_count(self.tmp), 1)
        self.assertEqual(entries.pending_count(self.tmp), 1)

    def test_inbox_stats(self):
        ib = entries.inbox_stats(self.tmp)
        self.assertEqual(ib['total'], 2)
        self.assertEqual(ib['conf'], 1)
        self.assertEqual(ib['bad'], [])

    def test_files_scope(self):
        files = entries.inbox_files(self.tmp)
        self.assertEqual([os.path.basename(p) for p in files], ['2026-01-01.md'])


class TestConf(unittest.TestCase):
    def test_normalize(self):
        cases = {
            '实测': '实测', '源码+实测': '实测', '设备实测': '实测',
            '代码/单测实测，**设备验收待补**': '实测',
            '推断': '推断', '文档核验': '推断',
            '推算': '推算', '待核': '待核',
            '决定': None, '用户令（aio-ops §9.1）': None, 'unknown': None,
        }
        for k, v in cases.items():
            self.assertEqual(entries.normalize_conf(k), v, k)

    def test_parse_conf(self):
        self.assertEqual(entries.parse_conf('- [fact] x | conf: 实测 → 归位: a.md'), '实测')
        self.assertIsNone(entries.parse_conf('- [fact] x | conf: 决定 y'))
        self.assertIsNone(entries.parse_conf('- [fact] x | owner: 用户'))
        # 文件名/配置键里的 .conf: 不算
        self.assertIsNone(entries.parse_conf('- [fact] 见 _meta/agents.conf:pi 行'))


class TestHeadCount(unittest.TestCase):
    def test_no_git_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'inbox'))
            self.assertIsNone(entries.head_marker_count(td))

    @unittest.skipUnless(shutil.which('git'), 'git 不在 PATH')
    def test_head_vs_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'inbox'))
            p = os.path.join(td, 'inbox', '2026-01-01.md')
            with open(p, 'w', encoding='utf-8') as f:
                f.write('- [fact] 已标记 → 归位: lines/a.md\n')
            env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@e',
                       GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@e')
            for cmd in (['init', '-q'], ['add', '.'], ['commit', '-qm', 'x']):
                subprocess.run(['git', '-C', td, *cmd], check=True, env=env,
                               capture_output=True)
            self.assertEqual(entries.head_marker_count(td), 1)
            self.assertEqual(entries.marker_count(td), 1)
            with open(p, 'a', encoding='utf-8') as f:
                f.write('- [fact] 新标记 → 归位: lines/b.md\n')
            self.assertEqual(entries.head_marker_count(td), 1)
            self.assertEqual(entries.marker_count(td), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)

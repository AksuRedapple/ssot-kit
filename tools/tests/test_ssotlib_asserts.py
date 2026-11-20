#!/usr/bin/env python3
"""回归：ssotlib.asserts 是断言解析的唯一实现。

守卫：
  - `^## A\\d+` 不再散落在工具里（sp_index / alloc / compile 都引用同一实现）
  - A515b 这类后缀块不丢、不误当重复
  - 缺号统计排除分配器预留；dup/missing/tags 口径与迁移前一致
"""
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import asserts  # noqa: E402

DOC = """## A1 · 第一条 · 实测
状态：现役｜标签：索引,检索
正文
## A2 · 第二条
状态：已过时｜superseded_by: A7
## A2 · 重复号
## A4 · 第四条
## A7b · 后缀块
状态：空号｜标签：编号
"""


class TestParse(unittest.TestCase):
    def test_blocks_and_fields(self):
        blocks = asserts.parse_text(DOC)
        self.assertEqual([b['id'] for b in blocks], ['A1', 'A2', 'A2', 'A4', 'A7b'])
        b = blocks[0]
        self.assertEqual(b['title'], '第一条 · 实测')
        self.assertEqual((b['status'], b['tags']), ('active', ['索引', '检索']))
        self.assertEqual(blocks[1]['status'], 'superseded')
        self.assertEqual(blocks[1]['superseded_by'], 'A7')
        self.assertEqual(blocks[4]['status'], 'vacant')
        self.assertEqual(blocks[4]['line'], 8)

    def test_ids_and_numbers(self):
        self.assertEqual(asserts.numbers(DOC), [1, 2, 2, 4, 7])      # 忽略后缀
        self.assertEqual(asserts.ids(DOC)[-1], (7, 'b'))             # 后缀保留

    def test_empty_and_missing_file(self):
        self.assertEqual(asserts.parse_text(''), [])
        self.assertEqual(asserts.parse('/nonexistent/assertions.md'), [])


class TestLint(unittest.TestCase):
    def _root(self, doc=DOC, reserved=(3,)):
        td = tempfile.mkdtemp()
        os.makedirs(os.path.join(td, 'knowledge'))
        os.makedirs(os.path.join(td, 'profile'))
        with open(os.path.join(td, 'knowledge', 'assertions.md'), 'w', encoding='utf-8') as f:
            f.write(doc)
        with open(os.path.join(td, 'profile', '.assert-alloc.json'), 'w', encoding='utf-8') as f:
            f.write('{"next":8,"reserved":%s}' % list(reserved))
        return td

    def test_counts(self):
        d = asserts.lint(self._root())
        self.assertEqual(d['total'], 5)
        self.assertEqual(d['latest'], 7)
        self.assertEqual(d['dups'], 1)
        self.assertEqual(d['dup_ids'], ['A2'])
        self.assertEqual(d['missing'], 2)          # 3 被预留，不算缺号 → 5,6
        self.assertEqual(d['missing_ids'], [3, 5, 6])
        self.assertEqual(d['tags'], 2)

    def test_no_file(self):
        self.assertEqual(asserts.lint('/nonexistent'), {'total': 0})


class TestSingleTruth(unittest.TestCase):
    def test_tools_share_parser(self):
        import sp_assert_lib
        import sp_assert_meta
        import sp_assert_audit
        import sp_index
        import ssot_check
        self.assertIs(sp_assert_lib.parse, asserts.parse)
        self.assertIs(sp_assert_lib.CITE_RX, asserts.CITE_RX)
        self.assertIs(sp_assert_audit.parse, asserts.parse)
        self.assertIs(sp_assert_meta.parse, asserts.parse)
        self.assertIs(sp_index.sp_assert_lib.parse, asserts.parse)
        # ssot_check 的体检结果与共享实现一致
        td = self._fixture()
        try:
            self.assertEqual(ssot_check.assertion_lint(td), asserts.lint(td))
        finally:
            import shutil
            shutil.rmtree(td, ignore_errors=True)

    def _fixture(self):
        td = tempfile.mkdtemp()
        os.makedirs(os.path.join(td, 'knowledge'))
        with open(os.path.join(td, 'knowledge', 'assertions.md'), 'w', encoding='utf-8') as f:
            f.write(DOC)
        return td


if __name__ == '__main__':
    unittest.main(verbosity=2)

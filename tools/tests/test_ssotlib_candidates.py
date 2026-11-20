#!/usr/bin/env python3
"""回归：ssotlib.candidates 的文本工具 + sp_candidates 单一真相。

候选抽取/冲突判定的口径（归一化、2-gram、极性先否后肯）一旦漂移，
会让「同一命题换说法」判成两条、或把否定句判成肯定——静默且难查。
"""
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import candidates as c  # noqa: E402


class TestNorm(unittest.TestCase):
    def test_digits_and_punct(self):
        self.assertEqual(c.norm('实测 3 次，耗时 12.5ms！'), '实测 n 次 耗时 n ms')
        self.assertEqual(c.norm('  A   B  '), 'a b')

    def test_fp(self):
        self.assertEqual(c.fp('版本 3 上线'), c.fp('版本 9 上线'))   # 数字归一
        self.assertNotEqual(c.fp('版本上线'), c.fp('版本下线'))


class TestTokens(unittest.TestCase):
    def test_cjk_bigrams_and_words(self):
        t = c.tokens('索引重建 rebuild_index')
        self.assertIn('索引', t)
        self.assertIn('重建', t)
        self.assertIn('rebuild_index', t)
        self.assertNotIn('索', t)          # 单字不成 token


class TestSimilarity(unittest.TestCase):
    def test_jaccard_overlap(self):
        a, b = {'x', 'y'}, {'x', 'y', 'z'}
        self.assertAlmostEqual(c.jaccard(a, b), 2 / 3)
        self.assertAlmostEqual(c.overlap(a, b), 1.0)     # 换说法场景
        self.assertEqual(c.jaccard(set(), b), 0.0)
        self.assertEqual(c.overlap(set(), b), 0.0)


class TestPolarity(unittest.TestCase):
    def test_negation_first(self):
        self.assertEqual(c.polarity('不需要并发'), -1)     # 否定词含肯定词
        self.assertEqual(c.polarity('必须并发'), +1)
        self.assertEqual(c.polarity('并发跑过了'), 0)


class TestClaimCleanup(unittest.TestCase):
    def test_clean_claim(self):
        self.assertEqual(c.clean_claim('- **实测**：x'), '实测：x')
        self.assertEqual(c.clean_claim('1. `代码`'), '代码')

    def test_is_junk(self):
        self.assertTrue(c.is_junk('| a | b | c |'))       # 表格
        self.assertTrue(c.is_junk('太短'))                 # <12
        self.assertTrue(c.is_junk('苹果香蕉橘子葡萄西瓜桃子李子杏子'))  # 无谓语标记
        self.assertFalse(c.is_junk('实测：索引重建必须按版本目录切换，否则会读到旧库。'))
        self.assertTrue(c.is_junk('注：这是表注'))         # 以注:开头算 junk

    def test_sentences(self):
        got = list(c.sentences('第一句够长了可以切出来。太短\n第三句也够长了可以切出来！'))
        self.assertEqual(len(got), 2)
        self.assertTrue(all(8 <= len(x) <= 220 for x in got))


class TestSingleTruth(unittest.TestCase):
    def test_sp_candidates_uses_lib(self):
        import sp_candidates
        for name in ('norm', 'fp', 'tokens', 'jaccard', 'overlap', 'polarity',
                     'clean_claim', 'rstrip_lines', 'is_junk', 'sentences'):
            self.assertIs(getattr(sp_candidates, name), getattr(c, name), name)

    @unittest.skipUnless(os.path.exists(os.path.join(TOOLS, 'sp_candidate_dedup.py')),
                         'sp_candidate_dedup.py 只在私有实例（未随 kit 发布）')
    def test_dedup_no_longer_imports_tool(self):
        src = open(os.path.join(TOOLS, 'sp_candidate_dedup.py'), encoding='utf-8').read()
        self.assertNotIn("spec_from_file_location('sem'", src)
        self.assertNotIn('sp_semantic.py', src)
        self.assertIn('from ssotlib.index import embed', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)

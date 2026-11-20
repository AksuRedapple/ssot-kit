#!/usr/bin/env python3
"""回归：状态文件「存在但损坏」要告警；「不存在」保持静默。

动机：把缺失和损坏混为一谈，会让「没配」噪声化，或让「配坏了」无声降级
（分配器状态坏 → 撞号；策略坏 → 监控会话被纳入索引）。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_assert_alloc  # noqa: E402
from ssotlib import cli, policy  # noqa: E402
from ssotlib.index import layout  # noqa: E402


def corrupt(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{不是 JSON')


class Base(unittest.TestCase):
    def setUp(self):
        cli._WARNED.clear()


class TestAllocState(Base):
    def test_corrupt_warns_and_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'alloc.json')
            corrupt(p)
            old = sp_assert_alloc.STATE
            sp_assert_alloc.STATE = p
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(sp_assert_alloc._load(), {})
            finally:
                sp_assert_alloc.STATE = old
            self.assertIn('无法解析', err.getvalue())

    def test_missing_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            old = sp_assert_alloc.STATE
            sp_assert_alloc.STATE = os.path.join(td, 'nope.json')
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(sp_assert_alloc._load(), {})
            finally:
                sp_assert_alloc.STATE = old
            self.assertEqual(err.getvalue(), '')


class TestPolicy(Base):
    def test_corrupt_falls_back_to_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            corrupt(os.path.join(td, 'profile', 'index-policy.json'))
            with contextlib.redirect_stderr(io.StringIO()) as err:
                p = policy.load_policy(td)
            self.assertFalse(p['enabled'])
            self.assertEqual(p['skip'], ['automation', 'monitor'])
            self.assertIn('无法解析', err.getvalue())

    def test_missing_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                p = policy.load_policy(td)
            self.assertFalse(p['enabled'])
            self.assertEqual(err.getvalue(), '')

    def test_valid_not_warned(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'profile'))
            with open(os.path.join(td, 'profile', 'index-policy.json'), 'w') as f:
                json.dump({'include': ['human'], 'skip': ['monitor']}, f)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                p = policy.load_policy(td)
            self.assertTrue(p['enabled'])
            self.assertEqual(err.getvalue(), '')


class TestActivePointer(Base):
    def test_corrupt_warns_and_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            corrupt(os.path.join(td, 'active.json'))
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(layout.active_version(td))
            self.assertIn('无法解析', err.getvalue())

    def test_missing_is_silent(self):
        with tempfile.TemporaryDirectory() as td:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertIsNone(layout.active_version(td))
            self.assertEqual(err.getvalue(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""回归：ssotlib.cli 的退出码三态与 dry-run 旗标。"""
import contextlib
import io
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib import cli  # noqa: E402


class TestParser(unittest.TestCase):
    def test_root_default_and_override(self):
        ap = cli.base_parser(description='x')
        self.assertEqual(ap.parse_args([]).root, os.path.expanduser('~/ssot'))
        self.assertEqual(ap.parse_args(['--root', '/tmp/r']).root, '/tmp/r')

    def test_no_root(self):
        ap = cli.base_parser(root=False)
        self.assertFalse(hasattr(ap.parse_args([]), 'root'))

    def test_dry_run_flag(self):
        ap = cli.base_parser()
        cli.add_dry_run(ap)
        self.assertFalse(ap.parse_args([]).dry_run)
        self.assertTrue(ap.parse_args(['--dry-run']).dry_run)


class TestRun(unittest.TestCase):
    def test_ok_and_value(self):
        self.assertEqual(cli.run(lambda: None), 0)
        self.assertEqual(cli.run(lambda: 0), 0)
        self.assertEqual(cli.run(lambda: 3), 3)

    def test_instrument_vs_product(self):
        def instr():
            raise cli.InstrumentError('索引缺失')
        def prod():
            raise ValueError('校验不过')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.run(instr), 2)
        self.assertIn('索引缺失', err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.run(prod), 1)
        self.assertIn('ValueError', err.getvalue())

    def test_exit_code_map(self):
        self.assertEqual(cli.exit_code(cli.InstrumentError('x')), 2)
        self.assertEqual(cli.exit_code(ValueError('x')), 1)

    def test_system_exit_passes_through(self):
        def f():
            raise SystemExit(1)
        with self.assertRaises(SystemExit):
            cli.run(f)


if __name__ == '__main__':
    unittest.main(verbosity=2)

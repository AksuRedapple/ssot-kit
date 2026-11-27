#!/usr/bin/env python3
import os
import sys
import unittest
from unittest import mock

try:
    import numpy  # noqa: F401
except ImportError:
    print('SKIP: sp_semantic requires numpy')
    raise SystemExit(77)

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
import sp_semantic as S  # noqa: E402


class AcquireTimeoutTest(unittest.TestCase):
    def test_timeout_env_is_integer(self):
        captured = {}

        class Proc:
            returncode = 0
            stdout = ''
            stderr = ''

        def fake_run(args, **kwargs):
            captured.update(kwargs['env'])
            return Proc()

        with mock.patch('subprocess.run', side_effect=fake_run):
            self.assertTrue(S.ensure_semantic_daemon())
        self.assertEqual(captured['SSOT_SEMANTIC_ACQUIRE_TIMEOUT'], '20')

        captured.clear()
        with mock.patch.dict(os.environ, {'SSOT_SEMANTIC_ACQUIRE_TIMEOUT': '20.5'}):
            with mock.patch('subprocess.run', side_effect=fake_run):
                self.assertTrue(S.ensure_semantic_daemon())
        self.assertEqual(captured['SSOT_SEMANTIC_ACQUIRE_TIMEOUT'], '20')


if __name__ == '__main__':
    unittest.main(verbosity=2)

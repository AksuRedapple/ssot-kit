#!/usr/bin/env python3
"""回归：坏 JSON 行不再静默丢弃，必须计数并警告（每处只报一次）。"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_candidates  # noqa: E402
import sp_retire_candidates  # noqa: E402
import sp_triage  # noqa: E402
from ssotlib import cli  # noqa: E402


def write(path, rows, bad=0):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
        for _ in range(bad):
            f.write('{坏行\n')


class TestWarnOnceReset(unittest.TestCase):
    def setUp(self):
        cli._WARNED.clear()


class TestCandidatesLedger(TestWarnOnceReset):
    def test_bad_line_counted(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'candidates.jsonl')
            write(p, [{'fingerprint': 'f1', 'claim': 'x'}], bad=1)
            old = sp_candidates.OUT
            sp_candidates.OUT = p
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    idx = sp_candidates.load_index()
            finally:
                sp_candidates.OUT = old
            self.assertIn('f1', idx)
            out = err.getvalue()
            self.assertIn('跳过 1 行', out)
            self.assertEqual(out.count('跳过'), 1)     # warn_once 去重

    def test_clean_no_warning(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'candidates.jsonl')
            write(p, [{'fingerprint': 'f1'}])
            old = sp_candidates.OUT
            sp_candidates.OUT = p
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    sp_candidates.load_index()
            finally:
                sp_candidates.OUT = old
            self.assertNotIn('跳过', err.getvalue())


class TestTriageLedger(TestWarnOnceReset):
    def test_both_readers_warn_once(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'candidates.jsonl')
            write(p, [{'claim': 'c', 'evidence': [{'session': 'sess-abc', 'line': 3}]}], bad=1)
            old = sp_triage.LEDGER
            sp_triage.LEDGER = p
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    items = sp_triage.extract_from_ledger('abc')
                    total, eligible = sp_triage.ledger_counts('abc')
            finally:
                sp_triage.LEDGER = old
            self.assertEqual(len(items), 1)
            self.assertEqual((total, eligible), (1, 1))
            self.assertIn('跳过 1 行', err.getvalue())
            self.assertEqual(err.getvalue().count('跳过'), 1)


class TestRetireLog(TestWarnOnceReset):
    def test_bad_line_counted(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'search-log.jsonl')
            write(p, [{'ts': '2026-11-20T00:00:00+08:00',
                       'tool': 'sp_semantic', 'topk_sids': ['12345678']}], bad=1)
            old = sp_retire_candidates.LOG
            sp_retire_candidates.LOG = p
            try:
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    hits, logs = sp_retire_candidates.load_hits(180)
            finally:
                sp_retire_candidates.LOG = old
            self.assertEqual(logs, 1)
            self.assertIn('12345678', hits)
            self.assertIn('跳过 1 行', err.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)

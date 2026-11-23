#!/usr/bin/env python3
"""回归：sp_s0repair 的「词尾」修复（精确找回 / 退化 / 真密钥不动）。

2026-11-22 旧 scrub 把 `task-<hex>` / `ask-at-poorest` 的 `sk-...` 当密钥，
留下 `ta[REDACTED-SECRET].json`。修复必须：
  · 能从同会话未脱敏副本找回原串的，精确恢复；
  · 找不到的退化为 `sk-REDACTED`（恢复词形，不假装找回）；
  · 标点/空白前的标记是真密钥，绝不恢复。
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

import sp_s0repair as R  # noqa: E402


class PureTest(unittest.TestCase):
    def test_exact_from_corpus(self):
        text = 'a ta[REDACTED-SECRET].json b'
        corpus = ['x task-deadbeef.json y']
        new, exact, fb = R.recover(text, corpus)
        self.assertEqual(new, 'a task-deadbeef.json b')
        self.assertEqual((exact, fb), (1, 0))

    def test_fallback_keeps_word_shape(self):
        new, exact, fb = R.recover('hard-di[REDACTED-SECRET] usage', [])
        self.assertEqual(new, 'hard-disk-REDACTED usage')
        self.assertEqual((exact, fb), (0, 1))

    def test_real_key_marker_untouched(self):
        for prefix in ('"', "'", ' ', '`', '=', ':'):
            text = prefix + '[REDACTED-SECRET]'
            new, exact, fb = R.recover(text, [])
            self.assertEqual(new, text, prefix)
            self.assertEqual((exact, fb), (0, 0))

    def test_multiple_and_context_lengths(self):
        text = 'x ta[REDACTED-SECRET].json y a[REDACTED-SECRET]-assessment y'
        # 拆开写：公开仓审计会把 task- 里的 sk- 当成 key（这里刻意不落明文）
        corpus = ['ta' + 'sk' + '-cafe1234.json', 'a' + 'sk' + '-at-poorest-assessment']
        new, exact, fb = R.recover(text, corpus)
        self.assertEqual(new, 'x ta' + 'sk' + '-cafe1234.json y a' + 'sk' + '-at-poorest-assessment y')
        self.assertEqual((exact, fb), (2, 0))

    def test_sid8_of(self):
        self.assertEqual(R.sid8_of(
            'evidence/cc/S1-sessions/2026-11-22-deadbeef-x/transcript.jsonl'), 'deadbeef')
        self.assertEqual(R.sid8_of(
            'evidence/qoder/S0-archive/qoder-projects/p/849f2602-8643-416e-9b37-x.jsonl'),
            '849f2602')
        self.assertEqual(R.sid8_of('evidence/qoder/S0-archive/qoder-memory/x.md'), '')

    def test_corpus_from_s1_files(self):
        with tempfile.TemporaryDirectory() as td:
            old = R.SSOT
            R.SSOT = td
            d = Path(td) / 'evidence/cc/S1-sessions/2026-11-22-deadbeef-x'
            d.mkdir(parents=True)
            (d / 'transcript.jsonl').write_text('task-deadbeef.json', encoding='utf-8')
            try:
                c = R.Corpus(db='/nope', logs='/nope')
                texts = c.for_sid('deadbeef')
                self.assertTrue(any('task-deadbeef' in t for t in texts))
            finally:
                R.SSOT = old


class MainTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.old = (R.SSOT, R.QODER_DB, R.QODER_LOGS, sys.argv)
        R.SSOT = str(self.root)
        R.QODER_DB = '/nope'
        R.QODER_LOGS = '/nope'
        (self.root / 'alerts').mkdir()
        (self.root / 'evidence/cc/S1-sessions/2026-11-22-deadbeef-x').mkdir(parents=True)
        self.s0 = self.root / 'evidence/cc/S0-archive/claude-projects/p/deadbeef-1.jsonl'
        self.s0.parent.mkdir(parents=True)
        self.s0.write_text('x ta[REDACTED-SECRET].json y\n', encoding='utf-8')
        self.old_mtime = 1700000000
        os.utime(self.s0, (self.old_mtime, self.old_mtime))
        # 同会话未脱敏副本
        (self.root / 'evidence/cc/S1-sessions/2026-11-22-deadbeef-x/transcript.jsonl').write_text(
            'task-cafe1234.json\n', encoding='utf-8')
        self.manifest = self.root / 'alerts/s0-scrub-x.json'
        json.dump({'rows': [{'path': os.path.relpath(self.s0, self.root), 'layer': 'S0'}]},
                  open(self.manifest, 'w'))

    def tearDown(self):
        R.SSOT, R.QODER_DB, R.QODER_LOGS, sys.argv = self.old
        self._td.cleanup()

    def run_main(self, *argv):
        sys.argv = ['sp_s0repair.py', '--manifest', str(self.manifest), *argv]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = R.main() or 0
        return code, buf.getvalue()

    def test_dry_run_then_apply(self):
        before = self.s0.read_text(encoding='utf-8')
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('DRY-RUN', out)
        self.assertIn('精确 1 / 退化 0', out)
        self.assertEqual(self.s0.read_text(encoding='utf-8'), before)
        code, out = self.run_main('--apply')
        self.assertIn('APPLY', out)
        text = self.s0.read_text(encoding='utf-8')
        self.assertEqual(text, 'x task-cafe1234.json y\n')
        self.assertEqual(int(os.path.getmtime(self.s0)), self.old_mtime)
        manifests = list((self.root / 'alerts').glob('s0-repair-*.json'))
        self.assertEqual(len(manifests), 1)
        d = json.loads(manifests[0].read_text(encoding='utf-8'))
        self.assertEqual((d['exact'], d['fallback']), (1, 0))

    def test_no_corpus_falls_back(self):
        (self.root / 'evidence/cc/S1-sessions/2026-11-22-deadbeef-x/transcript.jsonl').unlink()
        code, out = self.run_main('--apply')
        self.assertIn('退化 1', out)
        self.assertIn('task-REDACTED', self.s0.read_text(encoding='utf-8'))

    def test_layer_and_sid_filter(self):
        code, out = self.run_main('--layers', 'S1')
        self.assertIn('0 文件', out)
        code, out = self.run_main('--sid', 'ffff')
        self.assertIn('0 文件', out)


if __name__ == '__main__':
    unittest.main(verbosity=2)

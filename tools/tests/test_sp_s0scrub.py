#!/usr/bin/env python3
"""回归：sp_s0scrub 的 S0 就地脱敏（只替换密钥片段，不动其余字节）。

S0 是 S1/索引的上游；脱敏工具本身错一次，不可逆。判据：
  · 只替换命中片段，JSONL 仍可解析
  · mtime 必须保留（否则增量全量重转）
  · dry-run 绝不落盘；--apply 写清单（只有路径/计数/哈希）
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_s0scrub as S  # noqa: E402

SECRET = 'sk-' + 'a' * 30
BEARER = 'Bearer ' + 'b' * 40


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.s0 = self.root / 'evidence' / 'cc' / 'S0-archive' / 'proj' / 'sid'
        self.s0.mkdir(parents=True)
        self.old = (S.SSOT, sys.argv)
        S.SSOT = str(self.root)

    def tearDown(self):
        S.SSOT, sys.argv = self.old
        self._td.cleanup()

    def run_main(self, *argv):
        sys.argv = ['sp_s0scrub.py', *argv]
        buf = io.StringIO()
        code = 0
        with redirect_stdout(buf):
            try:
                code = S.main() or 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, buf.getvalue()

    def write(self, name, text):
        p = self.s0 / name
        p.write_text(text, encoding='utf-8')
        return p


class ScrubTest(Base):
    def test_scrub_text_counts(self):
        new, counts, total = S.scrub_text(f'a {SECRET} b {BEARER}')
        self.assertNotIn(SECRET, new)
        self.assertIn('[REDACTED-SECRET]', new)
        self.assertEqual(total, 2)
        self.assertEqual(sum(counts), 2)

    def test_dry_run_writes_nothing(self):
        p = self.write('a.jsonl', json.dumps({'t': SECRET}) + '\n')
        before = p.read_bytes()
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn('DRY-RUN', out)
        self.assertIn('1 文件 / 1 处', out)
        self.assertEqual(p.read_bytes(), before)
        self.assertFalse((self.root / 'alerts').exists())

    def test_apply_scrubs_and_keeps_mtime_and_json(self):
        p = self.write('a.jsonl', json.dumps({'t': SECRET, 'n': 1}, ensure_ascii=False) + '\n')
        old_mtime = 1700000000
        os.utime(p, (old_mtime, old_mtime))
        code, out = self.run_main('--apply')
        self.assertEqual(code, 0)
        self.assertIn('APPLY', out)
        lines = p.read_text(encoding='utf-8').splitlines()
        d = json.loads(lines[0])
        self.assertNotIn(SECRET, d['t'])
        self.assertEqual(d['n'], 1)
        self.assertEqual(int(os.path.getmtime(p)), old_mtime)
        manifests = list((self.root / 'alerts').glob('s0-scrub-*.json'))
        self.assertEqual(len(manifests), 1)
        m = json.loads(manifests[0].read_text(encoding='utf-8'))
        self.assertEqual(m['files'], 1)
        self.assertEqual(m['matches'], 1)
        self.assertEqual(m['rows'][0]['sha256_before'],
                         json.loads(manifests[0].read_text())['rows'][0]['sha256_before'])
        self.assertNotEqual(m['rows'][0]['sha256_before'], m['rows'][0]['sha256_after'])
        # 幂等：再跑 0 文件
        code, out = self.run_main('--apply')
        self.assertIn('0 文件 / 0 处', out)

    def test_broken_jsonl_is_skipped(self):
        p = self.write('bad.jsonl', '{not json ' + SECRET + '\n')
        before = p.read_bytes()
        code, out = self.run_main('--apply')
        self.assertEqual(code, 0)
        self.assertEqual(p.read_bytes(), before)
        self.assertIn('0 文件', out)

    def test_only_filter(self):
        self.write('a.jsonl', json.dumps({'t': SECRET}) + '\n')
        other = self.root / 'evidence' / 'pi' / 'S0-archive' / 'p' / 's'
        other.mkdir(parents=True)
        (other / 'b.jsonl').write_text(json.dumps({'t': SECRET}), encoding='utf-8')
        code, out = self.run_main('--only', 'pi')
        self.assertIn('1 文件 / 1 处', out)
        self.assertIn('pi/', out)

    def test_markdown_and_no_match_files(self):
        self.write('a.md', f'说明 {SECRET}\n')
        self.write('b.md', '没有密钥\n')
        code, out = self.run_main('--apply', '--quiet')
        self.assertIn('1 文件 / 1 处', out)
        self.assertIn('[REDACTED-SECRET]', (self.s0 / 'a.md').read_text(encoding='utf-8'))
        self.assertEqual((self.s0 / 'b.md').read_text(encoding='utf-8'), '没有密钥\n')

    def test_scope_evidence_includes_s1_and_scope_s0_excludes(self):
        d = self.root / 'evidence' / 'cc' / 'S1-sessions' / 'x'
        d.mkdir(parents=True)
        (d / 't.jsonl').write_text(json.dumps({'t': SECRET}), encoding='utf-8')
        code, out = self.run_main('--scope', 's0')
        self.assertIn('0 文件 / 0 处', out)
        self.assertIn(SECRET, (d / 't.jsonl').read_text(encoding='utf-8'))
        code, out = self.run_main('--apply')
        self.assertIn('1 文件 / 1 处', out)
        self.assertNotIn(SECRET, (d / 't.jsonl').read_text(encoding='utf-8'))

    def test_manifest_records_layer(self):
        d = self.root / 'evidence' / 'cc' / 'S1-sessions' / 'x'
        d.mkdir(parents=True)
        (d / 'raw.jsonl').write_text(json.dumps({'t': SECRET}), encoding='utf-8')
        self.run_main('--apply')
        m = json.loads(next((self.root / 'alerts').glob('s0-scrub-*.json')).read_text())
        self.assertEqual(m['rows'][0]['layer'], 'S1-raw')


if __name__ == '__main__':
    unittest.main(verbosity=2)

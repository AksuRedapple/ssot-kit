#!/usr/bin/env python3
"""回归：sp_drafts --backfill（P4）。

背景：草稿只在 stop-draft 钩子触发时产生，早于钩子/其他入口创建的会话
永远不进 `_pending`。backfill 只读反扫 S1，列出「有内容但无草稿」的候选。
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

import sp_drafts as D  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.old = (D.SSOT, D.PENDING, D.REGISTRY, sys.argv)
        D.SSOT = str(self.root)
        D.PENDING = str(self.root / 'sessions' / '_pending')
        D.REGISTRY = str(self.root / 'sessions' / 'registry.md')
        (self.root / 'sessions' / '_pending').mkdir(parents=True)
        (self.root / 'sessions' / 'registry.md').write_text('', encoding='utf-8')

    def tearDown(self):
        D.SSOT, D.PENDING, D.REGISTRY, sys.argv = self.old
        self._td.cleanup()

    def s1(self, sid, counts=None, smoke=False, rows=0, title='会话'):
        d = self.root / 'evidence/cc/S1-sessions' / f'2026-11-22-{sid[:8]}-x'
        d.mkdir(parents=True)
        json.dump({'sid': sid, 'title': title, 'cwd': '/opt/x', 'smoke': smoke,
                   'start': '2026-11-22T01:00:00Z',
                   'counts': counts if counts is not None else {'user': 1, 'assistant': 1}},
                  open(d / 'meta.json', 'w'))
        with open(d / 'transcript.jsonl', 'w', encoding='utf-8') as f:
            for i in range(rows):
                f.write(json.dumps({'role': 'user', 'kind': 'text',
                                    'content': f'第 {i} 行，足够长的内容'}) + '\n')
        return d

    def draft(self, sid8):
        (self.root / 'sessions' / '_pending' / f'{sid8}.md').write_text(
            f'- 2026-11-22 01:00:00 | sid: {sid8}-0000 | cwd: /x\n', encoding='utf-8')

    def run_main(self, *argv):
        sys.argv = ['sp_drafts.py', *argv]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = D.main() or 0
        return code, buf.getvalue()


class BackfillTest(Base):
    def test_lists_only_content_without_draft(self):
        self.s1('aaaa1111-0000', title='有草稿')
        self.draft('aaaa1111')
        self.s1('bbbb2222-0000', title='有内容无草稿')
        self.s1('cccc3333-0000', counts={'user': 0, 'assistant': 0}, rows=0, title='空壳')
        self.s1('dddd4444-0000', smoke=True, title='烟测')
        code, out = self.run_main('--backfill', '--json')
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d['backfill'], 1)
        self.assertEqual(d['rows'][0]['sid8'], 'bbbb2222')
        self.assertEqual(d['rows'][0]['title'], '有内容无草稿')

    def test_retired_excluded(self):
        self.s1('eeee5555-0000', title='已退休')
        (self.root / 'profile').mkdir()
        (self.root / 'profile' / 'retired.jsonl').write_text(
            json.dumps({'sid': 'eeee5555-0000', 'op': 'retire'}) + '\n', encoding='utf-8')
        code, out = self.run_main('--backfill', '--json')
        self.assertEqual(json.loads(out)['backfill'], 0)

    def test_old_meta_without_counts_uses_transcript_lines(self):
        d = self.s1('ffff6666-0000', rows=3, title='旧 meta')
        json.dump({'sid': 'ffff6666-0000', 'title': '旧 meta'}, open(d / 'meta.json', 'w'))
        code, out = self.run_main('--backfill', '--json')
        rows = json.loads(out)['rows']
        self.assertEqual(len(rows), 1)
        self.assertGreater(rows[0]['lines'], 0)

    def test_text_output_and_limit(self):
        self.s1('aaaa7777-0000', title='甲')
        self.s1('bbbb8888-0000', title='乙')
        code, out = self.run_main('--backfill', '--limit', '1')
        self.assertIn('有内容但无草稿的会话 1 个', out)
        self.assertIn('只读候选', out)

    def test_no_files_written(self):
        self.s1('bbbb9999-0000')
        before = sorted(os.listdir(D.PENDING))
        self.run_main('--backfill')
        self.assertEqual(sorted(os.listdir(D.PENDING)), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)

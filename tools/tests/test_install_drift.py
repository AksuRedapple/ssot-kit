#!/usr/bin/env python3
"""回归：ssot_check [install-drift]（批次 5 P0/P1）。

2026-11-23 事故：setup.sh/update.sh 只拷 `ssotlib/*.py`，v0.30 拆出的
`ssotlib/index/` 子包安装后永久缺失，语义检索 ImportError。
判据：缺子包必须阻断；steward.sh 本地定制只提示不阻断。
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

import ssot_check as C  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name) / 'ssot'
        self.kit = Path(self._td.name) / 'kit'
        (self.root / 'tools').mkdir(parents=True)
        (self.root / 'sessions').mkdir()
        (self.root / 'sessions' / 'registry.md').write_text('', encoding='utf-8')
        self.old = os.environ.get('SSOT_KIT')
        os.environ['SSOT_KIT'] = str(self.kit)

    def tearDown(self):
        if self.old is None:
            os.environ.pop('SSOT_KIT', None)
        else:
            os.environ['SSOT_KIT'] = self.old
        self._td.cleanup()

    def touch(self, base, rel, text=''):
        p = Path(base) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def test_missing_index_subpackage_blocks(self):
        self.touch(self.root, 'tools/sp_semantic.py')
        issues = C.install_drift(str(self.root))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0][1], 'missing')
        self.assertIn('ssotlib/index', issues[0][0])

    def test_index_present_no_issue(self):
        self.touch(self.root, 'tools/sp_semantic.py')
        self.touch(self.root, 'tools/ssotlib/index/__init__.py')
        self.assertEqual(C.install_drift(str(self.root)), [])

    def test_kit_tree_missing_files(self):
        self.touch(self.kit, 'tools/ssotlib/index/pack.py')
        self.touch(self.kit, 'tools/ssotlib/store.py')
        self.touch(self.root, 'tools/ssotlib/store.py')
        issues = C.install_drift(str(self.root))
        rels = [x[0] for x in issues]
        self.assertIn('tools/ssotlib/index/pack.py', rels)
        self.assertNotIn('tools/ssotlib/store.py', rels)

    def test_steward_mismatch_is_stale_not_blocking(self):
        self.touch(self.kit, 'tools/steward.sh', 'kit-version\n')
        self.touch(self.root, 'tools/steward.sh', 'local-custom\n')
        issues = C.install_drift(str(self.root))
        stale = [x for x in issues if x[1] == 'stale']
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0][0], 'tools/steward.sh')

    def test_main_reports_blocking_and_warning(self):
        self.touch(self.root, 'tools/sp_semantic.py')
        self.touch(self.kit, 'tools/steward.sh', 'kit\n')
        self.touch(self.root, 'tools/steward.sh', 'local\n')
        old = sys.argv
        buf = io.StringIO()
        code = 0
        try:
            sys.argv = ['ssot_check.py', '--root', str(self.root)]
            with redirect_stdout(buf):
                try:
                    C.main()
                except SystemExit as e:
                    code = e.code or 0
        finally:
            sys.argv = old
        out = buf.getvalue()
        self.assertIn('[install-drift] ❌ 1 项框架文件缺失', out)
        self.assertIn('[install-drift] ⚠ tools/steward.sh', out)
        self.assertIn('1 项需处理', out)

    def test_main_clean(self):
        self.touch(self.root, 'tools/sp_semantic.py')
        self.touch(self.root, 'tools/ssotlib/index/__init__.py')
        old = sys.argv
        buf = io.StringIO()
        try:
            sys.argv = ['ssot_check.py', '--root', str(self.root)]
            with redirect_stdout(buf):
                try:
                    C.main()
                except SystemExit:
                    pass
        finally:
            sys.argv = old
        self.assertIn('[install-drift] 框架文件完整', buf.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)

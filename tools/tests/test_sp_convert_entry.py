#!/usr/bin/env python3
"""test_sp_convert_entry · sp_convert 入口冒烟（A561）。

2026-11-21 事故：模块级常量块被重构删掉，库函数测试全绿，`main()` 一跑就
NameError，steward 的转换任务静默失败 29 小时。判据不是「--help 能跑」，
而是「真实子命令能产出 S1 五件套」。

做法：把模块的 VAULT / SRCS 指到临时目录，喂一个最小 cc 会话，
跑 `--src cc --sid deadbeef --force`，断言产物存在且 meta 正确。
"""
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import sp_convert  # noqa: E402
from ssotlib import pending as sp_pending  # noqa: E402


class ConvertEntryTest(unittest.TestCase):
    def test_cc_minimal_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            s0 = os.path.join(tmp, 'S0')
            s1 = os.path.join(tmp, 'S1')
            d = os.path.join(s0, 'proj')
            os.makedirs(d)
            sid = 'deadbeef-1111-2222-3333-444455556666'
            rows = [
                {'type': 'user', 'uuid': 'u1', 'timestamp': '2026-11-22T01:00:00Z',
                 'cwd': tmp, 'message': {'role': 'user', 'content': '入口冒烟测试'}},
                {'type': 'assistant', 'uuid': 'a1', 'parentUuid': 'u1',
                 'timestamp': '2026-11-22T01:00:05Z',
                 'message': {'role': 'assistant',
                             'content': [{'type': 'text', 'text': '收到'}]}},
            ]
            src = os.path.join(d, sid + '.jsonl')
            with open(src, 'w', encoding='utf-8') as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')

            old = (sp_convert.VAULT, dict(sp_convert.SRCS), sp_convert.S0,
                   sp_convert.S1, sp_convert.CUR_SRC, sys.argv)
            old_pending = (sp_pending.SSOT, sp_pending.MARK, getattr(sp_pending, 'LOCK', None))
            try:
                # 待索引标记也要隔离，否则测试会把真实 pending-index.json 改成 2 会话
                sp_pending.SSOT = tmp
                sp_pending.MARK = os.path.join(tmp, 'S2-index', 'pending-index.json')
                sp_pending.LOCK = sp_pending.MARK + '.lock'
                sp_convert.VAULT = tmp
                sp_convert.SRCS['cc'] = (os.path.relpath(s0, tmp),
                                         os.path.relpath(s1, tmp))
                sp_convert.S0 = s0
                sp_convert.S1 = s1
                sp_convert.CUR_SRC = 'cc'
                sys.argv = ['sp_convert.py', '--src', 'cc',
                            '--sid', 'deadbeef', '--force']
                sp_convert.main()
            finally:
                (sp_convert.VAULT, sp_convert.SRCS, sp_convert.S0,
                 sp_convert.S1, sp_convert.CUR_SRC, sys.argv) = old
                sp_pending.SSOT, sp_pending.MARK, _lk = old_pending
                if _lk is not None:
                    sp_pending.LOCK = _lk

            outs = [x for x in os.listdir(s1) if 'deadbeef' in x]
            self.assertEqual(len(outs), 1, f'S1 产物数不对: {outs}')
            out = os.path.join(s1, outs[0])
            for fn in ('meta.json', 'transcript.jsonl', 'transcript.md'):
                self.assertTrue(os.path.exists(os.path.join(out, fn)), fn)
            meta = json.load(open(os.path.join(out, 'meta.json'), encoding='utf-8'))
            self.assertEqual(meta['src'], 'cc')
            self.assertEqual(meta['sid'], sid)
            self.assertGreater(meta['counts']['user'], 0)

    def test_module_constants_defined(self):
        """常量块是本事故的直接死因：钉住它们的存在。"""
        for name in ('VAULT', 'SRCS', 'S0', 'S1', 'CONVERTER', 'CUR_SRC'):
            self.assertTrue(hasattr(sp_convert, name), f'缺模块常量 {name}')
        self.assertTrue(callable(sp_convert.contract_schema))
        self.assertTrue(callable(sp_convert.lstr))


if __name__ == '__main__':
    unittest.main()

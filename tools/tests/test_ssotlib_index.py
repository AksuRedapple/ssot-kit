#!/usr/bin/env python3
"""回归：ssotlib.index 的布局、向量包、嵌入调用。

重点不是「函数能跑」，而是：
  - active 指针/根清单是原子写，legacy 单库能兜底
  - 向量包 noop / append / rebuild 三条路径都被走到（真实索引不会重写包）
  - doc/query 前缀成对定义，sp_index 与 sp_semantic 引用同一份布局实现
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

from ssotlib.index import embed, layout, pack  # noqa: E402

HAS_NUMPY = importlib.util.find_spec('numpy') is not None


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute('create table chunks(id integer primary key, path text, line integer, '
                'text text, role text, ts text, vec blob)')
    for rid, vec in rows:
        con.execute('insert into chunks(id, vec) values(?,?)',
                    (rid, struct.pack(f'<{len(vec)}f', *vec)))
    con.commit()
    con.close()


class TestLayout(unittest.TestCase):
    def test_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            make_db(os.path.join(td, 'index.db'), [(1, [1.0, 0.0])])
            self.assertIsNone(layout.active_version(td))
            self.assertEqual(layout.resolve_db(td), os.path.join(td, 'index.db'))

    def test_set_active_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            v1 = os.path.join(td, 'versions', 'v1')
            os.makedirs(v1)
            make_db(os.path.join(v1, 'index.db'), [(1, [1.0, 0.0])])
            with open(os.path.join(v1, 'BUILD.json'), 'w', encoding='utf-8') as f:
                json.dump({'chunks': 1, 'built_at': '2026-01-01'}, f)
            layout.set_active('v1', td)

            self.assertEqual(layout.active_version(td), 'v1')
            self.assertEqual(layout.resolve_db(td), os.path.join(v1, 'index.db'))
            self.assertEqual(open(os.path.join(v1, 'STATUS'), encoding='utf-8').read().strip(), 'active')
            root = json.load(open(os.path.join(td, 'BUILD.json'), encoding='utf-8'))
            self.assertEqual(root['active'], 'v1')
            self.assertEqual(root['db'], 'versions/v1/index.db')
            self.assertEqual(root['chunks'], 1)        # 版本清单字段保留
            self.assertEqual([v[1] for v in layout.list_versions(td)], ['active'])

    def test_prune_keeps_active(self):
        with tempfile.TemporaryDirectory() as td:
            for name in ('old', 'new'):
                d = os.path.join(td, 'versions', name)
                os.makedirs(d)
                make_db(os.path.join(d, 'index.db'), [(1, [1.0, 0.0])])
            layout.set_active('new', td)
            removed = layout.prune_versions(keep=0, sem=td)
            self.assertNotIn('new', removed)
            self.assertTrue(os.path.isdir(os.path.join(td, 'versions', 'new')))


class TestPack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, 'index.db')
        make_db(self.db, [(1, [1.0, 0.0]), (2, [0.0, 1.0]), (3, [1.0, 1.0])])
        self.vecs, self.ids = layout.pack_paths(self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_is_stdlib_only(self):
        n, _secs = pack.build_pack(self.db, self.vecs, self.ids, quiet=True)
        self.assertEqual(n, 3)
        self.assertEqual(os.path.getsize(self.vecs), 3 * 2 * 4)
        self.assertEqual(os.path.getsize(self.ids), 3 * 8)
        self.assertTrue(pack.pack_fresh(self.db, self.vecs, self.ids))

    @unittest.skipUnless(HAS_NUMPY, 'numpy 不在：向量包读路径跳过（写路径仍测）')
    def test_load(self):
        pack.build_pack(self.db, self.vecs, self.ids, quiet=True)
        M, ids = pack.load_pack(self.vecs, self.ids)
        self.assertEqual(tuple(ids), (1, 2, 3))
        self.assertEqual(M.shape, (3, 2))

    @unittest.skipUnless(HAS_NUMPY, 'numpy 不在：增量/压实路径需要 numpy')
    def test_incremental_paths(self):
        pack.build_pack(self.db, self.vecs, self.ids, quiet=True)

        r = pack.build_pack_incremental(self.db, self.vecs, self.ids, quiet=True)
        self.assertEqual(r['mode'], 'noop')

        con = sqlite3.connect(self.db)
        con.execute('insert into chunks(id, vec) values(4, ?)', (struct.pack('<2f', 0.5, 0.5),))
        con.commit(); con.close()
        r = pack.build_pack_incremental(self.db, self.vecs, self.ids, quiet=True)
        self.assertEqual((r['mode'], r['appended']), ('append', 1))
        _M, ids = pack.load_pack(self.vecs, self.ids)
        self.assertEqual(tuple(ids), (1, 2, 3, 4))

        # 缺太多 → 回退全量压实
        con = sqlite3.connect(self.db)
        con.executemany('insert into chunks(id, vec) values(?, ?)',
                        [(i, struct.pack('<2f', 1.0, float(i))) for i in range(5, 12)])
        con.commit(); con.close()
        r = pack.build_pack_incremental(self.db, self.vecs, self.ids, quiet=True, max_missing=2)
        self.assertEqual(r['mode'], 'rebuild')
        _M, ids = pack.load_pack(self.vecs, self.ids)
        self.assertEqual(len(ids), 11)


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n))
        out = json.dumps({'data': [{'embedding': [0.1, 0.2]} for _ in body['input']]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class TestEmbed(unittest.TestCase):
    def test_prefixes_paired(self):
        self.assertTrue(embed.DOC_PREFIX.startswith('title:'))
        self.assertTrue(embed.QUERY_PREFIX.startswith('task:'))
        self.assertNotEqual(embed.DOC_PREFIX, embed.QUERY_PREFIX)

    def test_batch_and_one(self):
        srv = ThreadingHTTPServer(('127.0.0.1', 0), _H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            api = f'http://127.0.0.1:{srv.server_address[1]}/v1/embeddings'
            self.assertEqual(embed.embed_batch(['a', 'b'], api=api), [[0.1, 0.2], [0.1, 0.2]])
            self.assertEqual(embed.embed_one('a', api=api), [0.1, 0.2])
        finally:
            srv.shutdown()


class TestSingleTruth(unittest.TestCase):
    def test_sp_index_shared_layout(self):
        import sp_index
        for name in ('active_version', 'resolve_db', 'list_versions',
                     'write_root_manifest', 'set_active', 'prune_versions'):
            self.assertIs(getattr(sp_index, name), getattr(layout, name), name)
        self.assertIs(sp_index._pack, pack)
        self.assertEqual(sp_index.DOC_PREFIX, embed.DOC_PREFIX)

    @unittest.skipUnless(HAS_NUMPY, 'numpy 不在：sp_semantic 导入即需要 numpy')
    def test_sp_semantic_shared(self):
        import sp_semantic
        self.assertIs(sp_semantic._layout, layout)
        self.assertIs(sp_semantic._embed, embed)
        self.assertEqual(sp_semantic.API, embed.API)
        self.assertEqual(sp_semantic.QUERY_PREFIX, embed.QUERY_PREFIX)
        # sp_semantic 保留 daemon 注入点：load_pack 必须读 _PACK_OVERRIDE
        self.assertIsNone(sp_semantic._PACK_OVERRIDE)


if __name__ == '__main__':
    unittest.main(verbosity=2)

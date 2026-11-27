#!/usr/bin/env python3
import os
import sys
import unittest
import urllib.error
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
from ssotlib.index import embed  # noqa: E402


class EmbedLazyTest(unittest.TestCase):
    def setUp(self):
        self.old_api, self.old_default, self.old_lease = embed.API, embed.DEFAULT_API, embed.LEASE

    def tearDown(self):
        embed.API, embed.DEFAULT_API, embed.LEASE = self.old_api, self.old_default, self.old_lease

    def test_custom_api_does_not_acquire(self):
        embed.DEFAULT_API = 'http://127.0.0.1:8399/v1/embeddings'
        embed.API = 'http://127.0.0.1:12345/v1/embeddings'
        with mock.patch.object(embed, '_post', return_value=[[1.0]]) as post:
            with mock.patch('subprocess.run') as run:
                with mock.patch.object(embed, '_touch_lease') as touch:
                    self.assertEqual(embed.embed_batch(['x']), [[1.0]])
                    touch.assert_not_called()
                run.assert_not_called()
                post.assert_called_once()

    def test_local_requests_renew_lease_even_when_ensure_is_cached(self):
        embed.DEFAULT_API = embed.API = 'http://127.0.0.1:8399/v1/embeddings'
        with mock.patch.object(embed, 'ensure_local', return_value=True):
            with mock.patch.object(embed, '_post', return_value=[[1.0]]):
                with mock.patch.object(embed, '_touch_lease') as touch:
                    embed.embed_batch(['x'])
                    embed.embed_batch(['y'])
                    self.assertEqual(touch.call_count, 2)

    def test_connection_error_forces_acquire_and_retry(self):
        embed.DEFAULT_API = embed.API = 'http://127.0.0.1:8399/v1/embeddings'
        with mock.patch.object(embed, 'ensure_local', side_effect=[True, True]) as ensure:
            with mock.patch.object(embed, '_post', side_effect=[urllib.error.URLError('down'), [[2.0]]]) as post:
                self.assertEqual(embed.embed_batch(['x']), [[2.0]])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(ensure.call_count, 2)
        self.assertTrue(ensure.call_args_list[1].kwargs.get('force'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

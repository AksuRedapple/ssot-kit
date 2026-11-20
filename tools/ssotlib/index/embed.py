"""嵌入服务调用：doc / query 前缀成对定义（索引侧与查询侧必须配套）。

改前缀就是改索引口径——两处必须在同一文件里改，避免「索引用了 doc 前缀、
查询用了另一个」这种静默降质。
"""
import json
import os
import urllib.request

API = os.environ.get('SSOT_EMBED_API', 'http://127.0.0.1:8399/v1/embeddings')
DOC_PREFIX = 'title: none | text: '
QUERY_PREFIX = 'task: search result | query: '


def embed_batch(texts, timeout=300, api=None):
    """批量取向量（顺序与输入一致，已 L2 归一化）。"""
    req = urllib.request.Request(
        api or API,
        data=json.dumps({'input': list(texts)}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return [x['embedding'] for x in d['data']]


def embed_one(text, timeout=60, api=None):
    """单条取向量（查询侧用；超时比批量短，检索要快失败）。"""
    return embed_batch([text], timeout=timeout, api=api)[0]

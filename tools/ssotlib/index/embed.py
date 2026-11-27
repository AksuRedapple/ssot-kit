"""嵌入服务调用：doc / query 前缀成对定义（索引侧与查询侧必须配套）。

改前缀就是改索引口径——两处必须在同一文件里改，避免「索引用了 doc 前缀、
查询用了另一个」这种静默降质。
"""
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request

DEFAULT_API = 'http://127.0.0.1:8399/v1/embeddings'
API = os.environ.get('SSOT_EMBED_API', DEFAULT_API)
LEASE = os.environ.get('SSOT_EG2_LEASE', '/tmp/ssot-eg2.want')
DOC_PREFIX = 'title: none | text: '
QUERY_PREFIX = 'task: search result | query: '
ACQUIRE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       'sp_eg2_acquire.sh')

_last_ensure = 0.0
_ensure_lock = threading.Lock()


def _is_local_default(api):
    return (api or API).rstrip('/') == DEFAULT_API.rstrip('/')


def ensure_local(force=False, timeout=None):
    """确保默认本地 :8399 已拉起；非默认 API、测试假服务不触发。"""
    global _last_ensure
    if os.environ.get('SSOT_EG2_ACQUIRE') == '0' or not _is_local_default(API):
        return False
    now = time.monotonic()
    if not force and now - _last_ensure < 60:
        return True
    timeout = max(1, int(float(timeout or os.environ.get('SSOT_EG2_ACQUIRE_TIMEOUT', '60'))))
    with _ensure_lock:
        now = time.monotonic()
        if not force and now - _last_ensure < 60:
            return True
        env = os.environ.copy()
        env['SSOT_EG2_ACQUIRE_TIMEOUT'] = str(timeout)
        try:
            proc = subprocess.run(['/bin/bash', ACQUIRE], capture_output=True, text=True,
                                  timeout=timeout + 5, env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError('eg2 acquire timeout')
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or 'eg2 acquire failed').strip()[:200])
        _last_ensure = time.monotonic()
    return True


def _touch_lease():
    """每次真实本地 embedding 请求都续租；60s ensure 缓存不能替代消费者心跳。"""
    try:
        parent = os.path.dirname(LEASE)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(LEASE, 'a', encoding='utf-8'):
            pass
        os.utime(LEASE, None)
    except OSError:
        pass


def _post(texts, timeout, api):
    req = urllib.request.Request(
        api,
        data=json.dumps({'input': list(texts)}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return [x['embedding'] for x in d['data']]


def embed_batch(texts, timeout=300, api=None):
    """批量取向量（顺序与输入一致，已 L2 归一化）。"""
    api = api or API
    local = _is_local_default(api)
    if local:
        ensure_local()
        _touch_lease()
    try:
        return _post(texts, timeout, api)
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        if not local:
            raise
        ensure_local(force=True)
        _touch_lease()
        return _post(texts, timeout, api)


def embed_one(text, timeout=60, api=None):
    """单条取向量（查询侧用；超时比批量短，检索要快失败）。"""
    return embed_batch([text], timeout=timeout, api=api)[0]

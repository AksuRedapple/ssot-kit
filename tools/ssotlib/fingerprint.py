"""嵌入环境指纹（bench / BUILD / --status 共用）

只读：硬件、模型 md5 前 12、llama-server 版本、backend。
"""
import hashlib
import json
import os
import platform
import subprocess
import sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))


def _default_model():
    p = os.environ.get('EMBED_MODEL')
    if p:
        return os.path.expanduser(p)
    try:
        d = json.load(open(os.path.join(SSOT, 'profile', 'embed-profile.json'), encoding='utf-8'))
        p = d.get('model_path') or (d.get('model') or {}).get('path')
        if p:
            return os.path.expanduser(p)
    except Exception:
        pass
    return os.path.join(SSOT, 'models', 'embeddinggemma-2-BF16.gguf')


MODEL = _default_model()


def _mem_bytes():
    try:
        if sys.platform == 'darwin':
            return int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'],
                                               text=True, stderr=subprocess.DEVNULL).strip())
        for line in open('/proc/meminfo', encoding='utf-8', errors='replace'):
            if line.startswith('MemTotal:'):
                return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


def hardware_fp():
    mem = _mem_bytes()
    return '%s-%dg-%s-%dc' % (platform.machine(), round(mem / (1 << 30)) if mem else 0,
                              sys.platform, os.cpu_count() or 1)


def model_fp(path=None):
    path = os.path.expanduser(path or MODEL)
    if not os.path.isfile(path):
        return 'missing:' + os.path.basename(path)
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return 'unreadable'
    return h.hexdigest()[:12]


def llama_version(exe=None):
    exe = exe or os.environ.get('LLAMA_SERVER', 'llama-server')
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
        out = (r.stdout + r.stderr).strip().splitlines()
        return out[0] if out else 'unknown'
    except Exception:
        return 'unknown'


def backend():
    return '%s-%s' % (sys.platform, platform.machine())


def env(path=None):
    p = os.path.expanduser(path or MODEL)
    return {'hardware_fp': hardware_fp(), 'model_fp': model_fp(p),
            'model_path': p, 'llama_version': llama_version(),
            'backend': backend()}

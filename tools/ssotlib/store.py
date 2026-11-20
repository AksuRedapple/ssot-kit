"""JSON / JSONL 读写：原子写 + 坏行计数（纯标准库）。

写盘一律「临时文件 + os.replace」，避免半截文件；读盘对坏行/坏 JSON 显式计数，
不再用裸 `except: pass` 把数据问题吞掉。
"""
import json
import os
import tempfile


class JsonlStats(dict):
    """read_jsonl 的返回：dict 同时可当 (rows, bad) 解包。"""

    def __iter__(self):
        yield self['rows']
        yield self['bad']

    @property
    def rows(self):
        return self['rows']

    @property
    def bad(self):
        return self['bad']


def read_json(path, default=None):
    """读 JSON；文件不存在或内容坏掉 → default（调用方必须显式给出默认值）。"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_json_strict(path, default=None, label=None):
    """读 JSON：**不存在**→静默给 default；**存在但坏了**→default + 警告一次。"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        from . import cli
        cli.warn_once('corrupt:' + str(path),
                      f'{label or path}: 文件存在但无法解析（{e}），已回退默认值')
        return default


def iter_jsonl(path):
    """→ 生成器 (lineno, obj|None)；坏行给 None，由调用方决定计数还是中断。"""
    try:
        f = open(path, encoding='utf-8')
    except OSError:
        return
    with f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield lineno, json.loads(line)
            except ValueError:
                yield lineno, None


def read_jsonl(path):
    """→ {rows, bad}（也可 `rows, bad = read_jsonl(p)`）；坏行跳过并计数。"""
    rows, bad = [], 0
    for _lineno, obj in iter_jsonl(path):
        if obj is None:
            bad += 1
        else:
            rows.append(obj)
    return JsonlStats(rows=rows, bad=bad)


def _atomic_write(path, write_body, mode=0o600, fsync=False):
    """公共原子写：同目录临时文件 → chmod → os.replace。"""
    path = os.path.abspath(path)
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.' + os.path.basename(path) + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            write_body(f)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json_atomic(path, obj, indent=2, ensure_ascii=False, sort_keys=False,
                      mode=0o600, fsync=False):
    """原子写 JSON（默认 0600：SSOT 的 profile/状态文件常含本机路径）。"""
    def body(f):
        json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent, sort_keys=sort_keys)
        f.write('\n')
    _atomic_write(path, body, mode=mode, fsync=fsync)


def write_jsonl_atomic(path, rows, mode=0o600, fsync=False):
    """原子写 JSONL：逐行 dump，末尾换行。"""
    def body(f):
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    _atomic_write(path, body, mode=mode, fsync=fsync)


def append_jsonl(path, obj, mode=0o600):
    """追加一行 JSONL；目录自动建，文件权限固定 0600。"""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        f.flush()
    try:
        os.chmod(path, mode)
    except OSError:
        pass

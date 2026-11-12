#!/usr/bin/env python3
"""sp_assert_alloc · 断言编号分配器(并发安全)

问题:多会话同时写 assertions.md 时,各自 max+1 → 撞号(2026-11-04 一天撞 5 次)。
做法:flock 锁 + 计数文件 + 预留表;分配即预留,写入后 commit 释放预留。

用法:
  python3 tools/sp_assert_alloc.py --next 3      # 预留 3 个编号,打印
  python3 tools/sp_assert_alloc.py --status      # 下一个编号 / 已预留
  python3 tools/sp_assert_alloc.py --commit 521 522   # 写入完成后释放预留
  python3 tools/sp_assert_alloc.py --sync        # 以文件最大号重置计数(谨慎)
"""
import argparse, fcntl, glob, json, os, re, sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
ASSERT = os.path.join(SSOT, 'knowledge', 'assertions.md')
STATE = os.path.join(SSOT, 'profile', '.assert-alloc.json')
LOCK = os.path.join(SSOT, 'profile', '.assert-alloc.lock')


def _max_in_file():
    if not os.path.exists(ASSERT):
        return 0
    txt = open(ASSERT, encoding='utf-8', errors='replace').read()
    nums = [int(m) for m in re.findall(r'^## A(\d+)', txt, re.M)]
    return max(nums) if nums else 0


def _load():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    json.dump(d, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def _locked():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    fh = open(LOCK, 'a+')
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def alloc(n=1):
    fh = _locked()
    try:
        d = _load()
        nxt = int(d.get('next') or (_max_in_file() + 1))
        nxt = max(nxt, _max_in_file() + 1)
        reserved = set(int(x) for x in d.get('reserved', []))
        ids = []
        while len(ids) < n:
            while nxt in reserved:
                nxt += 1
            ids.append(nxt); reserved.add(nxt); nxt += 1
        d['next'] = nxt
        d['reserved'] = sorted(reserved)
        _save(d)
        return ids
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def commit(ids):
    fh = _locked()
    try:
        d = _load()
        res = set(int(x) for x in d.get('reserved', []))
        for i in ids:
            res.discard(int(i))
        d['reserved'] = sorted(res)
        _save(d)
        return sorted(res)
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close()


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_assert_alloc.py --next 2\n  sp_assert_alloc.py --commit 521',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--next', type=int, default=0)
    ap.add_argument('--commit', nargs='+', type=int, default=[])
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--sync', action='store_true')
    a = ap.parse_args()
    if a.next:
        print(' '.join('A%d' % i for i in alloc(a.next))); return 0
    if a.commit:
        print('剩余预留:', commit(a.commit)); return 0
    if a.sync:
        fh = _locked()
        try:
            d = _load(); d['next'] = _max_in_file() + 1; _save(d)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
        print(f'计数已重置为 A{_max_in_file()+1}'); return 0
    d = _load()
    # 与 alloc() 的自愈口径一致：文件里已有更大的号时，以文件为准
    nxt = max(int(d.get('next') or 1), _max_in_file() + 1)
    print(f"下一个 A{nxt} · 已预留 {d.get('reserved') or '无'}")
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

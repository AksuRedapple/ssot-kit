#!/usr/bin/env python3
"""sp_pending · 懒触发采集 → 定时索引的交接标记

流程：
  sp_convert 写 S2-index/pending-index.json（sessions/est_blocks）
  steward 读 sp_index --plan --json 的精确 pending_blocks，按阈值/窗口决定 run|defer|skip
  sp_index 成功后按 generation 清除（--no-pack 时保留 pack_stale）

用法:
  sp_pending.py --status
  sp_pending.py --merge --sessions 12 --est-blocks 8000 --by-session abc
  sp_pending.py --decide --json
  sp_pending.py --mark-pack-stale
  sp_pending.py --clear-if-settled
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
MARK = os.path.join(SSOT, 'S2-index', 'pending-index.json')
LOCK = MARK + '.lock'


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def load():
    try:
        with open(MARK, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _with_lock(fn):
    os.makedirs(os.path.dirname(MARK), exist_ok=True)
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception:
            pass
        return fn()
    finally:
        os.close(fd)


def _save(d):
    tmp = MARK + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, MARK)


def merge(sessions=0, est_blocks=0, by_session=None, pack_stale=None):
    def _do():
        d = load() or {'schema': 1, 'created_at': now(), 'generation': 0,
                       'sessions': 0, 'est_blocks': 0, 'settled': False,
                       'pack_stale': False}
        d.setdefault('schema', 1)
        d.setdefault('created_at', now())
        d['generation'] = int(d.get('generation') or 0) + 1
        d['sessions'] = int(d.get('sessions') or 0) + max(0, int(sessions))
        d['est_blocks'] = int(d.get('est_blocks') or 0) + max(0, int(est_blocks))
        d['updated_at'] = now()
        d['settled'] = False
        if by_session:
            d['by_session'] = by_session
        if pack_stale is not None:
            d['pack_stale'] = bool(pack_stale)
        _save(d)
        return d
    return _with_lock(_do)


def mark_pack_stale():
    def _do():
        d = load()
        if not d:
            return {}
        d['pack_stale'] = True
        d['updated_at'] = now()
        _save(d)
        return d
    return _with_lock(_do)


def plan_pending():
    """调 sp_index --plan --json 取精确 pending。失败返回 None。"""
    tool = os.path.join(SSOT, 'tools', 'sp_index.py')
    if not os.path.isfile(tool):
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sp_index.py')
    try:
        r = subprocess.run([sys.executable, tool, '--plan', '--json'],
                           capture_output=True, text=True, timeout=180, cwd=SSOT)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except Exception:
        return None


def clear_if_settled(pending_blocks=None):
    plan = plan_pending() if pending_blocks is None else {'pending_blocks': pending_blocks}
    if plan is None:
        return False
    blocks = int(plan.get('pending_blocks') or 0)
    d = load()
    if blocks == 0 and not d.get('pack_stale'):
        try:
            os.remove(MARK)
        except OSError:
            pass
        return True
    if d:
        d['pending_blocks'] = blocks
        d['settled'] = False
        d['updated_at'] = now()
        _with_lock(lambda: _save(d))
    return False


def after_index(start_generation, no_pack, changed):
    d = load()
    if not d:
        return
    if int(d.get('generation') or 0) != int(start_generation or 0):
        return                      # 索引期间又来了新转换，保留
    if no_pack and changed:
        mark_pack_stale()
        return
    try:
        os.remove(MARK)
    except OSError:
        pass


def clear_pack_stale_if_settled():
    """--pack-only 成功后用：pending=0 时即使 pack_stale 也清。"""
    plan = plan_pending()
    if plan is None:
        return False
    if int(plan.get('pending_blocks') or 0) != 0:
        return False
    try:
        os.remove(MARK)
        return True
    except OSError:
        return False


def _window_ok(window):
    if not window or window.lower() in ('any', 'off', '0'):
        return True
    try:
        a, b = window.split('-', 1)
        nowt = datetime.datetime.now().time()
        t1 = datetime.datetime.strptime(a.strip(), '%H:%M').time()
        t2 = datetime.datetime.strptime(b.strip(), '%H:%M').time()
        if t1 <= t2:
            return t1 <= nowt <= t2
        return nowt >= t1 or nowt <= t2
    except Exception:
        return True


def _policy():
    try:
        return json.load(open(os.path.join(SSOT, 'profile', 'steward-index.json'),
                              encoding='utf-8'))
    except Exception:
        return {}


def decide(threshold=None, window=None, force=False):
    cfg = _policy()
    threshold = int(threshold if threshold is not None else
                    os.environ.get('SSOT_STEWARD_INDEX_THRESHOLD',
                                   cfg.get('threshold', 50000)))
    window = window if window is not None else os.environ.get(
        'SSOT_STEWARD_INDEX_WINDOW', cfg.get('window', '') or '')
    force = force or os.environ.get('SSOT_STEWARD_INDEX_FORCE') == '1' or bool(cfg.get('force'))
    plan = plan_pending()
    if plan is None:
        return {'action': 'run', 'reason': 'plan_failed_fallback', 'pending_blocks': None}
    blocks = int(plan.get('pending_blocks') or 0)
    d = load()
    if blocks == 0:
        return {'action': 'skip', 'reason': 'no_pending', 'pending_blocks': 0, 'marker': d}
    if force:
        return {'action': 'run', 'reason': 'force', 'pending_blocks': blocks, 'marker': d}
    if not _window_ok(window):
        return {'action': 'defer', 'reason': 'outside_window', 'pending_blocks': blocks,
                'window': window, 'marker': d}
    if threshold > 0 and blocks > threshold:
        return {'action': 'defer', 'reason': 'over_threshold', 'pending_blocks': blocks,
                'threshold': threshold, 'marker': d}
    return {'action': 'run', 'reason': 'under_threshold', 'pending_blocks': blocks,
            'threshold': threshold, 'marker': d}


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_pending.py --decide --json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--sessions', type=int, default=0)
    ap.add_argument('--est-blocks', type=int, default=0)
    ap.add_argument('--by-session')
    ap.add_argument('--mark-pack-stale', action='store_true')
    ap.add_argument('--clear-if-settled', action='store_true')
    ap.add_argument('--decide', action='store_true')
    ap.add_argument('--threshold', type=int)
    ap.add_argument('--window')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.merge:
        d = merge(a.sessions, a.est_blocks, a.by_session)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else f"pending: sessions={d['sessions']} est_blocks={d['est_blocks']}")
        return 0
    if a.mark_pack_stale:
        d = mark_pack_stale()
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else 'pending: pack_stale=true')
        return 0
    if a.clear_if_settled:
        ok = clear_if_settled()
        print(json.dumps({'cleared': ok}, ensure_ascii=False) if a.json else ('cleared' if ok else 'kept'))
        return 0
    if a.decide:
        d = decide(a.threshold, a.window, a.force)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else
              f"action={d['action']} reason={d['reason']} pending={d.get('pending_blocks')}")
        return 0
    d = load()
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    elif d:
        print(f"pending: {d.get('sessions', 0)} 会话 / ~{d.get('est_blocks', 0)} 块 "
              f"· since {d.get('created_at', '-')} · generation {d.get('generation', 0)}")
    else:
        print('pending: 无')
    return 0


if __name__ == '__main__':
    sys.exit(main())

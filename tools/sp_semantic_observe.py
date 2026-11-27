#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from ssotlib.semantic_obs import idle_stats  # noqa: E402


def _query_stats(root, since=None):
    log = os.path.join(root, 'logs', 'semantic-daemon.log')
    lat = []
    since_dt = datetime.datetime.fromisoformat(since) if since else None
    if since_dt is not None and since_dt.tzinfo is not None:
        since_dt = since_dt.astimezone().replace(tzinfo=None)
    if os.path.exists(log):
        with open(log, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        start = 0
        for i, line in enumerate(lines):
            if 'ram-load' in line or 'listen ' in line:
                start = i
        for line in lines[start:]:
            try:
                ts = datetime.datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            if since_dt is not None and ts < since_dt:
                continue
            m = re.search(r'query ms=(\d+)', line)
            if m:
                lat.append(int(m.group(1)))
    lat = lat[-50:]
    p50 = p90 = 0
    if lat:
        ordered = sorted(lat)
        p50 = ordered[len(ordered) // 2]
        p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    fallback = queries = 0
    search_log = os.path.join(root, 'S2-index', 'search-log.jsonl')
    now = datetime.datetime.now().astimezone()
    cutoff = now - datetime.timedelta(hours=24)
    if os.path.exists(search_log):
        with open(search_log, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.datetime.fromisoformat(d['ts'])
                except Exception:
                    continue
                if ts < cutoff or (since_dt is not None and ts < since_dt.astimezone()):
                    continue
                queries += 1
                if d.get('status') == 'daemon_fallback':
                    fallback += 1
    fallback_rate = round(100 * fallback / queries, 2) if queries else 0.0
    return p50, p90, len(lat), fallback, queries, fallback_rate


def main():
    ap = argparse.ArgumentParser(description='记录 semantic 按需服务的每日观测')
    ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    ap.add_argument('--out', default=os.path.join(os.path.expanduser('~/ssot'),
                                                 'drafts/semantic-idle-reap/observations.jsonl'))
    ap.add_argument('--trigger', default='manual', help='manual / scheduled / reap / cold_probe')
    a = ap.parse_args()
    idle = idle_stats(a.root)
    p50, p90, n, fallback, queries, fallback_rate = _query_stats(a.root, idle['since'])
    footprint = ''
    pid = None
    state_path = os.environ.get('SSOT_SEMANTIC_STATE', '/tmp/ssot-semantic.state.json')
    try:
        with open(state_path, encoding='utf-8') as f:
            pid = json.load(f).get('pid')
        if pid:
            out = subprocess.run(['vmmap', '-summary', str(pid)], capture_output=True,
                                 text=True, timeout=10).stdout
            for line in out.splitlines():
                if 'Physical footprint:' in line:
                    footprint = line.strip()
                    break
    except Exception:
        pass
    top = subprocess.check_output(['top', '-l', '1', '-n', '0'], text=True)
    phys = next((x.strip() for x in top.splitlines() if 'PhysMem:' in x), '')
    swap = subprocess.check_output(['sysctl', 'vm.swapusage'], text=True).strip()
    rec = {
        'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'trigger': a.trigger,
        'state': idle['state'], 'active': idle['active'], 'idle_min': idle['idle_min'],
        'events_24h': dict(idle['24h']), 'events_7d': dict(idle['7d']),
        'last_event': idle['last'], 'query_p50_ms': p50, 'query_p90_ms': p90,
        'query_samples': n, 'query_window_hours': 24,
        'fallback_today': fallback, 'queries_today': queries,
        'fallback_rate_pct': fallback_rate,
        'wake_success_pct_24h': idle['24h']['wake_success_pct'],
        'cold_start_p95_s_24h': idle['24h']['cold_p95_s'], 'footprint': footprint,
        'physmem': phys, 'swap': swap,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    wake = rec['wake_success_pct_24h']
    cold_p95 = rec['cold_start_p95_s_24h']
    wake_s = 'n/a' if wake is None else f'{wake}%'
    cold_s = 'n/a' if cold_p95 is None else f'{cold_p95}s'
    print(f"[semantic-observe] state={rec['state']} idle={rec['idle_min']}m "
          f"wake={wake_s} cold_p95={cold_s} reaped24={idle['24h']['reaped']} "
          f"fallback={fallback}/{queries} ({fallback_rate}%) p50={p50}ms p90={p90}ms")
    return 0


if __name__ == '__main__':
    sys.exit(main())

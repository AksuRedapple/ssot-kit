import collections
import datetime
import json
import math
import os


def idle_stats(root):
    now = datetime.datetime.now().astimezone()
    path = os.path.join(root, 'logs', 'semantic-lifecycle.jsonl')
    since = None
    start_file = os.path.join(root, 'drafts', 'semantic-idle-reap', 'observation-start.json')
    if os.path.exists(start_file):
        try:
            with open(start_file, encoding='utf-8') as f:
                since = datetime.datetime.fromisoformat(json.load(f)['ts'])
        except Exception:
            since = None
    events = []
    manual_ts = set()
    manual_file = os.path.join(root, 'drafts', 'semantic-idle-reap', 'manual-reaps.json')
    if os.path.exists(manual_file):
        try:
            with open(manual_file, encoding='utf-8') as f:
                for item in json.load(f).get('reaps', []):
                    if isinstance(item, dict) and item.get('ts'):
                        manual_ts.add(str(item['ts']))
        except Exception:
            manual_ts = set()
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                    ts = datetime.datetime.fromisoformat(d['ts'])
                except Exception:
                    continue
                age = (now - ts).total_seconds()
                if age <= 7 * 86400 and (since is None or ts >= since):
                    events.append((age, d))

    def is_manual(d):
        return bool(d.get('manual')) or str(d.get('ts', '')) in manual_ts

    def quantile(values, q):
        values = sorted(values)
        return values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))]

    def counts(seconds):
        c = collections.Counter()
        cold_elapsed = []
        for age, d in events:
            if age > seconds:
                continue
            event = d.get('event', '?')
            if event == 'reaped' and is_manual(d):
                c['manual_reaped'] += 1
            else:
                c[event] += 1
            if event == 'acquire' and d.get('mode') == 'cold':
                c['cold_acquire'] += 1
            if event == 'ready' and d.get('mode') == 'cold':
                c['cold_ready'] += 1
                try:
                    cold_elapsed.append(float(d.get('elapsed_s', 0)))
                except (TypeError, ValueError):
                    pass
        c['wake_success_pct'] = None
        c['cold_p50_s'] = c['cold_p95_s'] = c['cold_max_s'] = None
        if c['cold_acquire']:
            c['wake_success_pct'] = round(100 * c['cold_ready'] / c['cold_acquire'], 1)
        if cold_elapsed:
            c['cold_p50_s'] = quantile(cold_elapsed, .5)
            c['cold_p95_s'] = quantile(cold_elapsed, .95)
            c['cold_max_s'] = max(cold_elapsed)
        return c

    state_path = os.environ.get('SSOT_SEMANTIC_STATE', '/tmp/ssot-semantic.state.json')
    state, idle_min, active = 'missing', None, None
    try:
        with open(state_path, encoding='utf-8') as f:
            d = json.load(f)
        active = int(d.get('active', 0))
        state = 'active' if active else ('stopping' if d.get('stopping') else 'running')
        idle_min = int(max(0, now.timestamp() - float(d.get('last_query', now.timestamp()))) / 60)
    except Exception:
        pass
    last = ''
    if events:
        _, d = min(events, key=lambda x: x[0])
        last = f"{d.get('event', '?')}@{datetime.datetime.fromisoformat(d['ts']).strftime('%m-%d %H:%M')}"
    return {'24h': counts(86400), '7d': counts(7 * 86400),
            'state': state, 'idle_min': idle_min, 'active': active, 'last': last,
            'since': since.isoformat() if since else None}

#!/usr/bin/env python3
import argparse
import collections
import datetime
import json
import math
import os
import re


def quantile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, max(0, math.ceil(q * len(values)) - 1))] if values else None


def amount_mib(token):
    m = re.search(r'(\d+(?:\.\d+)?)([KMG])', token or '')
    if not m:
        return None
    value = float(m.group(1))
    return value / 1024 if m.group(2) == 'K' else value if m.group(2) == 'M' else value * 1024


def memory_snapshot(d):
    fp = re.search(r'Physical footprint:\s*(\d+(?:\.\d+)?)([KMG])', d.get('footprint', ''))
    footprint_gib = float(fp.group(1)) if fp and fp.group(2) == 'G' else None
    phys = d.get('physmem', '')
    used = re.search(r'PhysMem:\s*(\d+(?:\.\d+)?[MG]) used', phys)
    compressor = re.search(r'(\d+(?:\.\d+)?[MG]) compressor', phys)
    unused = re.search(r'(\d+(?:\.\d+)?[MG]) unused', phys)
    swap = d.get('swap', '')
    swap_total = re.search(r'total\s*=\s*(\d+(?:\.\d+)?[MG])', swap)
    swap_used = re.search(r'used\s*=\s*(\d+(?:\.\d+)?[MG])', swap)
    return {'footprint_gib': footprint_gib,
            'phys_used_mib': amount_mib(used.group(1)) if used else None,
            'compressor_mib': amount_mib(compressor.group(1)) if compressor else None,
            'unused_mib': amount_mib(unused.group(1)) if unused else None,
            'swap_total_mib': amount_mib(swap_total.group(1)) if swap_total else None,
            'swap_used_mib': amount_mib(swap_used.group(1)) if swap_used else None}


def main():
    ap = argparse.ArgumentParser(description='汇总 semantic 按需化正式观测并给出调参建议')
    ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    ap.add_argument('--out', default=os.path.join(os.path.expanduser('~/ssot'),
                                                 'drafts/semantic-idle-reap/summary.md'))
    a = ap.parse_args()
    draft = os.path.join(a.root, 'drafts', 'semantic-idle-reap')
    since = None
    try:
        with open(os.path.join(draft, 'observation-start.json'), encoding='utf-8') as f:
            since = datetime.datetime.fromisoformat(json.load(f)['ts'])
    except Exception:
        pass
    fix_since = None
    try:
        with open(os.path.join(draft, 'fix-observation.json'), encoding='utf-8') as f:
            fix_since = datetime.datetime.fromisoformat(json.load(f)['ts'])
    except Exception:
        pass

    # 手工停服不计入「回收 idle」判断：事件的 manual=1，或登记在 manual-reaps.json。
    manual_reap_ts = set()
    try:
        with open(os.path.join(draft, 'manual-reaps.json'), encoding='utf-8') as f:
            for item in json.load(f).get('reaps', []):
                if isinstance(item, dict) and item.get('ts'):
                    manual_reap_ts.add(str(item['ts']))
    except Exception:
        pass

    def is_manual_reap(d):
        return bool(d.get('manual')) or str(d.get('ts', '')) in manual_reap_ts

    lifecycle = []
    path = os.path.join(a.root, 'logs', 'semantic-lifecycle.jsonl')
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.datetime.fromisoformat(d['ts'])
                except Exception:
                    continue
                if since is None or ts >= since:
                    lifecycle.append((ts, d))

    queries = []
    path = os.path.join(a.root, 'S2-index', 'search-log.jsonl')
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.datetime.fromisoformat(d['ts'])
                except Exception:
                    continue
                if since is None or ts >= since:
                    queries.append((ts, d))

    observations = []
    path = os.path.join(draft, 'observations.jsonl')
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ts = datetime.datetime.fromisoformat(d['ts'])
                except Exception:
                    continue
                if since is None or ts >= since:
                    observations.append((ts, d))

    observations.sort(key=lambda x: x[0])
    triggers = collections.Counter(d.get('trigger', 'manual') for _, d in observations)
    memory_release = []
    last_reap_ts = None
    for i, (ts, d) in enumerate(observations):
        if d.get('trigger') != 'reap':
            continue
        if is_manual_reap(d):
            continue
        if last_reap_ts is not None and (ts - last_reap_ts).total_seconds() < 5:
            continue
        last_reap_ts = ts
        prior = next(((pts, pd) for pts, pd in reversed(observations[:i])
                      if memory_snapshot(pd)['footprint_gib'] is not None), None)
        if prior is None:
            continue
        pts, pd = prior
        before, after = memory_snapshot(pd), memory_snapshot(d)
        delta = lambda key: (round(after[key] - before[key], 1)
                             if after[key] is not None and before[key] is not None else None)
        memory_release.append({'ts': ts.isoformat(), 'prior_ts': pts.isoformat(),
                               'prior_footprint_gib': before['footprint_gib'],
                               'unused_delta_mib': delta('unused_mib'),
                               'compressor_delta_mib': delta('compressor_mib'),
                               'swap_used_delta_mib': delta('swap_used_mib')})
    footprints = [x['prior_footprint_gib'] for x in memory_release]
    avg_reaped_footprint = round(sum(footprints) / len(footprints), 2) if footprints else None
    days = sorted(set(ts.date() for ts, _ in lifecycle) | set(ts.date() for ts, _ in queries))
    rows = []
    totals = collections.Counter()
    cold = []
    reap_idle = []
    for day in days:
        ev = [d for ts, d in lifecycle if ts.date() == day]
        qs = [d for ts, d in queries if ts.date() == day]
        c = collections.Counter(d.get('event', '?') for d in ev)
        cold_acquire = sum(d.get('event') == 'acquire' and d.get('mode') == 'cold' for d in ev)
        cold_ready = sum(d.get('event') == 'ready' and d.get('mode') == 'cold' for d in ev)
        cold += [float(d.get('elapsed_s', 0)) for d in ev
                 if d.get('event') == 'ready' and d.get('mode') == 'cold']
        natural_reaped = sum(d.get('event') == 'reaped' and not is_manual_reap(d) for d in ev)
        manual_reaped = sum(d.get('event') == 'reaped' and is_manual_reap(d) for d in ev)
        reap_idle += [float(d.get('idle_s', 0)) for d in ev
                      if d.get('event') == 'reaped' and d.get('idle_s') is not None
                      and not is_manual_reap(d)]
        fallback = sum(d.get('status') == 'daemon_fallback' for d in qs)
        attempts = len(qs)
        actual = attempts - fallback
        rows.append({
            'date': day.isoformat(), 'queries': actual, 'attempts': attempts,
            'fallback': fallback,
            'fallback_pct': round(100 * fallback / attempts, 2) if attempts else None,
            'cold_acquire': cold_acquire, 'cold_ready': cold_ready,
            'wake_pct': round(100 * cold_ready / cold_acquire, 1) if cold_acquire else None,
            'cold_p95_s': quantile([float(d.get('elapsed_s', 0)) for d in ev
                                    if d.get('event') == 'ready' and d.get('mode') == 'cold'], .95),
            'reaped': natural_reaped, 'manual_reaped': manual_reaped,
            'skip_active': c['skip_active'], 'skip_race': c['skip_race'],
            'failed': c['term_failed'] + c['state_invalid'] + c['acquire_timeout'],
        })
        totals['queries'] += actual
        totals['attempts'] += attempts
        totals['fallback'] += fallback
        totals['cold_acquire'] += cold_acquire
        totals['cold_ready'] += cold_ready
        totals['reaped'] += natural_reaped
        totals['manual_reaped'] += manual_reaped
        totals['skip_active'] += c['skip_active']
        totals['skip_race'] += c['skip_race']
        totals['failed'] += c['term_failed'] + c['state_invalid'] + c['acquire_timeout']

    post_events = [d for ts, d in lifecycle if fix_since is not None and ts >= fix_since]
    post_q = [d for ts, d in queries if fix_since is not None and ts >= fix_since]
    post_cold_acquire = sum(d.get('event') == 'acquire' and d.get('mode') == 'cold' for d in post_events)
    post_cold_ready = sum(d.get('event') == 'ready' and d.get('mode') == 'cold' for d in post_events)
    post_cold = [float(d.get('elapsed_s', 0)) for d in post_events
                 if d.get('event') == 'ready' and d.get('mode') == 'cold']
    post_fallback = sum(d.get('status') == 'daemon_fallback' for d in post_q)
    post_attempts = len(post_q)
    post_actual = post_attempts - post_fallback
    post_wake_pct = round(100 * post_cold_ready / post_cold_acquire, 1) if post_cold_acquire else None
    post_fallback_pct = round(100 * post_fallback / post_attempts, 2) if post_attempts else None
    post_cold_p95 = quantile(post_cold, .95)
    post_cold_rate = round(100 * post_cold_acquire / post_attempts, 2) if post_attempts else None
    post_reap_idle = [float(d.get('idle_s', 0)) for d in post_events
                      if d.get('event') == 'reaped' and d.get('idle_s') is not None
                      and not is_manual_reap(d)]
    post_reap_idle_min = min(post_reap_idle) if post_reap_idle else None
    post_reaped = sum(d.get('event') == 'reaped' and not is_manual_reap(d) for d in post_events)
    post_manual_reaped = sum(d.get('event') == 'reaped' and is_manual_reap(d) for d in post_events)
    post_failed = sum(d.get('event') in ('term_failed', 'state_invalid', 'acquire_timeout') for d in post_events)
    post_fix_sufficient = fix_since is not None and post_actual >= 5 and post_cold_acquire >= 2

    wake_pct = round(100 * totals['cold_ready'] / totals['cold_acquire'], 1) if totals['cold_acquire'] else None
    total_attempts = totals['queries'] + totals['fallback']
    fallback_pct = round(100 * totals['fallback'] / total_attempts, 2) if total_attempts else None
    cold_rate = round(100 * totals['cold_acquire'] / total_attempts, 2) if total_attempts else None
    cold_p95 = quantile(cold, .95)
    reap_idle_min = min(reap_idle) if reap_idle else None
    reap_idle_p50 = quantile(reap_idle, .5)
    if fix_since is not None:
        if not post_fix_sufficient:
            recommendation = (f'修复后窗口样本不足（查询 {post_actual}、冷唤醒 {post_cold_acquire}），'
                              '继续观测，不调冷却时间。')
        elif post_wake_pct < 99 or (post_fallback_pct or 0) > 1 or post_failed:
            recommendation = '修复后仍有唤醒/降级异常：先查故障，暂不调冷却时间。'
        elif post_reaped and post_reap_idle_min is not None and post_reap_idle_min < 1700:
            recommendation = '修复后回收 idle 异常：实际空闲不足约 30 分钟，先查 reaper/计时。'
        elif (post_cold_rate or 0) > 5:
            recommendation = '修复后冷启动占比 >5%：建议评估把冷却从 30 分钟调到 45 分钟。'
        elif (post_cold_rate or 0) < 2 and post_reaped > 0:
            recommendation = '修复后冷启动占比 <2% 且回收正常：可评估把冷却从 30 分钟缩到 20 分钟。'
        else:
            recommendation = '修复后冷启动占比 2–5%、唤醒/降级正常：保持 30 分钟。'
    elif not totals['queries'] or not totals['cold_acquire']:
        recommendation = '证据不足：正式窗口内查询或冷唤醒样本为 0，继续观测，不调冷却时间。'
    elif wake_pct < 99 or (fallback_pct or 0) > 1 or totals['failed']:
        recommendation = '先查唤醒/降级异常：唤醒率 <99%、fallback >1% 或有失败事件；暂不调冷却时间。'
    elif totals['reaped'] and reap_idle_min is not None and reap_idle_min < 1700:
        recommendation = '回收 idle 异常：实际空闲不足约 30 分钟，先查 reaper/计时，不调冷却时间。'
    elif (cold_rate or 0) > 5:
        recommendation = '冷启动占比 >5%：建议评估把冷却从 30 分钟调到 45 分钟。'
    elif (cold_rate or 0) < 2 and totals['reaped'] > 0:
        recommendation = '冷启动占比 <2% 且回收正常：可评估把冷却从 30 分钟缩到 20 分钟。'
    else:
        recommendation = '冷启动占比 2–5%、唤醒/降级正常：保持 30 分钟。'

    latest = observations[-1][1] if observations else {}
    summary = {
        'generated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'since': since.isoformat() if since else None,
        'fix_since': fix_since.isoformat() if fix_since else None,
        'post_fix': {'queries': post_actual, 'attempts': post_attempts, 'fallback': post_fallback,
                     'fallback_pct': post_fallback_pct, 'cold_acquire': post_cold_acquire,
                     'cold_ready': post_cold_ready, 'wake_pct': post_wake_pct,
                     'cold_p95_s': post_cold_p95, 'cold_rate_pct': post_cold_rate,
                     'reap_idle_min_s': post_reap_idle_min, 'reaped': post_reaped,
                     'failed': post_failed, 'sufficient': post_fix_sufficient},
        'days': rows, 'totals': dict(totals), 'wake_success_pct': wake_pct,
        'fallback_rate_pct': fallback_pct, 'cold_start_rate_pct': cold_rate,
        'cold_start_p95_s': cold_p95, 'reap_idle_min_s': reap_idle_min,
        'reap_idle_p50_s': reap_idle_p50, 'recommendation': recommendation,
        'observation_triggers': dict(triggers), 'latest_observation': latest,
        'manual_reaps_excluded': totals.get('manual_reaped', 0),
        'memory_release': memory_release, 'avg_reaped_footprint_gib': avg_reaped_footprint,
    }
    json_out = os.path.join(draft, 'summary.json')
    os.makedirs(draft, exist_ok=True)
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    lines = ['# semantic 按需化观测汇总', '',
             f"- 正式窗口：{summary['since'] or '未设置'}", f"- 生成：{summary['generated_at']}", '',
             '| 日期 | 查询 | fallback | 冷唤醒 | 唤醒率 | 冷启动 p95 | 回收 | skip_active | skip_race | failed |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    fmt = lambda v, suffix='': 'n/a' if v is None else f'{v}{suffix}'
    for r in rows:
        lines.append(f"| {r['date']} | {r['queries']} | {fmt(r['fallback_pct'], '%')} | "
                     f"{r['cold_acquire']} | {fmt(r['wake_pct'], '%')} | {fmt(r['cold_p95_s'], 's')} | "
                     f"{r['reaped']} | {r['skip_active']} | {r['skip_race']} | {r['failed']} |")
    lines += ['', f"- 总查询：{totals['queries']}（尝试 {total_attempts}）；冷启动占比：{fmt(cold_rate, '%')}",
              f"- 唤醒成功率：{fmt(wake_pct, '%')}；冷启动 p95：{fmt(cold_p95, 's')}",
              f"- fallback：{fmt(fallback_pct, '%')}；回收：{totals['reaped']}；失败：{totals['failed']}",
              f"- 修复后窗口（{fix_since.astimezone().strftime('%m-%d %H:%M') if fix_since else 'n/a'}）："
              f"查询 {post_actual}、wake {fmt(post_wake_pct, '%')}、cold p95 {fmt(post_cold_p95, 's')}、"
              f"冷启动占比 {fmt(post_cold_rate, '%')}、fallback {fmt(post_fallback_pct, '%')}、"
              f"回收 {post_reaped}、失败 {post_failed}、样本{'足够' if post_fix_sufficient else '不足'}",
              f"- 回收 idle：min {fmt(reap_idle_min, 's')} / p50 {fmt(reap_idle_p50, 's')}",
              f"- 观测来源：{dict(triggers)}",
              f"- 手工停服（不计入 idle）：{totals.get('manual_reaped', 0)} 次",
              f"- 回收前 footprint 均值：{fmt(avg_reaped_footprint, 'GiB')}", '']
    if memory_release:
        lines += ['| 回收时间 | 前次 footprint | unused Δ | compressor Δ | swap used Δ |',
                  '|---|---:|---:|---:|---:|']
        for r in memory_release:
            lines.append(f"| {r['ts'][:19].replace('T', ' ')} | {fmt(r['prior_footprint_gib'], 'GiB')} | "
                         f"{fmt(r['unused_delta_mib'], 'MiB')} | {fmt(r['compressor_delta_mib'], 'MiB')} | "
                         f"{fmt(r['swap_used_delta_mib'], 'MiB')} |")
        lines += ['', '> 内存差值是回收前后的观测变化，受系统其他进程影响，不作为单服务因果归因。', '']
    lines += [f"**建议：{recommendation}**", '']
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'wrote {a.out} and {json_out}')
    print(recommendation)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

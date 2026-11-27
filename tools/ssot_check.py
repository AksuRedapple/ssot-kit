#!/usr/bin/env python3
"""ssot_check · 本机知识中枢自查（只读，纯标准库）

用法: python3 ssot_check.py [--root ~/ssot] [--report PATH]

检查项:
  1. 登记册条目数 + 最近活动日期
  2. inbox 未提纯条数 + conf 标签覆盖率（实测/推断/待核）
  3. 线页数量 + 过期提醒（>30 天未更新）
  4. agent 记忆薄壳体积（若存在 ~/.qoder/memory/MEMORY.md，>24000B 告警）
  5. 断言库编号 lint（总数/最新/重复/缺号/标签数；只报不改号）
  6. 索引 built_at_commit（S2-index/semantic/BUILD.json 或 kb-index/BUILD.json）与 HEAD 对账
  7. 草稿/未尽工作/最近演练计数

--report PATH 额外生成一份短的 SSOT_REPORT.md（冷启动单文件入口）。
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re
import subprocess
import sys

# 允许 import 使用（测试/调试），不只当脚本跑：把自身目录放进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 条目/标记/conf 的唯一实现在 ssotlib.entries（A558 单一真相）；此处再导出给既有调用方与测试。
from ssotlib import asserts  # noqa: E402
from ssotlib.entries import (CONF_PREFIXES, ENTRY_RE, head_marker_count, inbox_stats,  # noqa: E402
                             is_entry, marker_count, normalize_conf, parse_conf, pending_count)
from ssotlib.semantic_obs import idle_stats as _semantic_idle_stats  # noqa: E402
from ssotlib import cli  # noqa: E402

# 与 sp_compile.HARD_LIMIT(25000) 对齐，告警线留 1000B 余量
MEM_WARN = 24000


def git(root, *args):
    try:
        return subprocess.check_output(['git', '-C', root, *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ''


def _versioned_build(root_build, data):
    """根 BUILD.json 只是在线清单：有 db/active 时，真正的读数在 versions/<v>/BUILD.json。

    2026-11-18：修复 --adopt/--full 后仍读根清单的 chunks/built_at，
    导致 [build] 长期显示迁移前的旧块数与旧构建时间。
    """
    base = os.path.dirname(root_build)
    db = data.get('db')
    if db:
        dbp = db if os.path.isabs(db) else os.path.join(base, db)
        cand = os.path.join(os.path.dirname(os.path.normpath(dbp)), 'BUILD.json')
        if os.path.exists(cand):
            return cand
    v = data.get('active')
    if v:
        cand = os.path.join(base, 'versions', str(v), 'BUILD.json')
        if os.path.exists(cand):
            return cand
    return None


def find_build(root):
    for rel in ('S2-index/semantic/BUILD.json', 'kb-index/BUILD.json'):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            try:
                with open(p, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                return p, {}
            vp = _versioned_build(p, data) if rel.startswith('S2-index/') else None
            if vp:
                try:
                    with open(vp, encoding='utf-8') as f:
                        return vp, json.load(f)
                except Exception:
                    pass
            return p, data
    return None, {}


def assertion_lint(root):
    """断言体检（解析与计数都在 ssotlib.asserts，只有一份实现）。"""
    return asserts.lint(root)


def fmt_ids(ids, cap=8):
    """[146,175,326,327,328] → 'A146,A175,326-328…'"""
    if not ids:
        return '-'
    if isinstance(ids[0], str):
        return ','.join(ids[:cap]) + ('…' if len(ids) > cap else '')
    parts, i = [], 0
    while i < len(ids) and len(parts) < cap:
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1:
            j += 1
        parts.append(str(ids[i]) if j == i else f'{ids[i]}-{ids[j]}')
        i = j + 1
    return ','.join(parts) + ('…' if i < len(ids) else '')


def capture_stats(root):
    """(staging 行数, 今日新增, alive 分钟, 上轮摘要) —— S1 观测两行"""
    import time as _t
    staging = os.path.join(root, 'inbox', '.staging')
    total = 0
    if os.path.isdir(staging):
        for fn in os.listdir(staging):
            if fn.endswith('.jsonl'):
                with open(os.path.join(staging, fn), encoding='utf-8') as f:
                    total += sum(1 for _ in f)
    seen = os.path.join(staging, '.seen')
    today = 0
    if os.path.exists(seen):
        mtime_day = datetime.date.today().isoformat()
        if datetime.date.fromtimestamp(os.path.getmtime(seen)).isoformat() == mtime_day:
            today = sum(1 for _ in open(seen, encoding='utf-8'))
    alive_min = None
    a = os.path.join(root, 'logs', 'capture-alive')
    if os.path.exists(a):
        alive_min = int((_t.time() - os.path.getmtime(a)) / 60)
    last = ''
    lg = os.path.join(root, 'logs', 'capture-sweep.log')
    if os.path.exists(lg):
        tail = [l.strip() for l in open(lg, encoding='utf-8', errors='replace') if l.strip()]
        if tail:
            last = tail[-1]
    return total, today, alive_min, last


def semantic_stats(root):
    """(p50, p90, 样本数, fallback 今日数) —— M2 常驻服务观测"""
    import json as _json
    import time as _t
    log = os.path.join(root, 'logs', 'semantic-daemon.log')
    lat = []
    if os.path.exists(log):
        lines = open(log, encoding='utf-8', errors='replace').read().splitlines()
        start = 0
        for i, ln in enumerate(lines):        # 只统计最近一次启动(ram-load 之后)的样本
            if 'ram-load' in ln or 'listen ' in ln:
                start = i
        for ln in lines[start:]:
            m = re.search(r'query ms=(\d+)', ln)
            if m:
                lat.append(int(m.group(1)))
    lat = lat[-50:]
    p50 = p90 = 0
    if lat:
        s = sorted(lat)
        p50 = s[len(s) // 2]
        p90 = s[min(len(s) - 1, int(len(s) * 0.9))]
    fb = 0
    sl = os.path.join(root, 'S2-index', 'search-log.jsonl')
    if os.path.exists(sl):
        day = _t.strftime('%F')
        for ln in open(sl, encoding='utf-8', errors='replace'):
            if day in ln[:30] and 'daemon_fallback' in ln:
                fb += 1
    return p50, p90, len(lat), fb


def semantic_idle_stats(root):
    """按需 semantic 生命周期观测（共享实现在 ssotlib.semantic_obs）。"""
    return _semantic_idle_stats(root)


def dispatch_stats(root):
    """(7 天内次数, 最近一次距今分钟) —— Phase B 消费端观测"""
    p = os.path.join(root, 'logs', 'dispatch.log')
    if not os.path.exists(p):
        return 0, None
    import json as _json
    now = datetime.datetime.now().astimezone()
    n7 = 0
    last = None
    for ln in open(p, encoding='utf-8', errors='replace'):
        try:
            d = _json.loads(ln)
            ts = datetime.datetime.fromisoformat(d['ts'])
        except Exception:
            continue
        age = (now - ts).total_seconds()
        if age <= 7 * 86400:
            n7 += 1
        if last is None or age < last:
            last = age
    return n7, (int(last / 60) if last is not None else None)


def citation_stats(root):
    """(被引用断言数, 总数) —— 知识是否被消费"""
    ap = os.path.join(root, 'knowledge', 'assertions.md')
    if not os.path.exists(ap):
        return 0, 0
    text = open(ap, encoding='utf-8').read()
    all_ids = set(re.findall(r'^## (A\d{3})', text, re.M))
    cited = set()
    for d in ('lines', 'knowledge'):   # 正本口径:inbox 是贡献流,不计入引用率
        for fn in glob.glob(os.path.join(root, d, '**', '*.md'), recursive=True):
            if fn.endswith('assertions.md'):
                continue
            try:
                cited |= set(re.findall(r'\bA\d{3}\b', open(fn, encoding='utf-8', errors='replace').read()))
            except Exception:
                continue
    return len(cited & all_ids), len(all_ids)


def coverage_line(root):
    """[coverage] 人类源 已索引/总 · 未接入 · tool 跳过"""
    import subprocess as _sp
    try:
        out = _sp.run([sys.executable, os.path.join(root, 'tools', 'sp_coverage.py'), '--json'],
                      capture_output=True, text=True, timeout=120)
        d = json.loads(out.stdout)
    except Exception:
        return None
    rows, pending = d.get('sources', []), d.get('pending', [])
    roles = {}
    try:
        roles = {k: v for k, v in json.load(open(os.path.join(root, 'profile', 'sources.json'), encoding='utf-8')).items()
                 if not k.startswith('_')}
    except Exception:
        pass
    human_raw = sum(r['raw'] for r in rows) + sum(p['raw'] for p in pending
                                                  if (roles.get(p['src']) or {}).get('role', 'human') != 'tool')
    idx = sum(r['covered'] for r in rows)
    miss = sum(p['raw'] for p in pending if (roles.get(p['src']) or {}).get('role', 'human') != 'tool')
    tool = sum(p['raw'] for p in pending if (roles.get(p['src']) or {}).get('role') == 'tool')
    # 未平账缺口 = 各源 S1(减空壳/策略跳过) 未覆盖量 + 未接入人类源；不能用 raw-idx（S1 可能多于 raw）
    unresolved = sum(r.get('gap_idx', 0) for r in rows) + miss
    skipped = sum(r.get('skipped', 0) for r in rows)
    denom = max(human_raw, idx)          # opencode raw 会随 DB 清理缩水；避免倒挂
    return idx, denom, miss, tool, unresolved, skipped


def pending_line(root):
    try:
        p = os.path.join(root, 'S2-index', 'pending-index.json')
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return None


def archive_line(root):
    p = os.path.join(root, 'alerts', 's0-scan.json')
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:
        return None
    try:
        pol = json.load(open(os.path.join(root, 'profile', 'evidence-policy.json'), encoding='utf-8'))
        d['_policy'] = pol
    except Exception:
        d['_policy'] = {}
    return d


def dead_path_examples(tk, limit=3):
    """从 takeover detail 里取前几条死路径，格式：线页.md:L601 tools/x.sh。"""
    out = []
    for page, rules in (tk.get('detail') or {}).items():
        for msg in (rules.get('R3') or []):
            m = re.match(r'L(\d+)\s+路径不存在:\s*(.+)$', msg)
            if m:
                out.append(f"{page}:L{m.group(1)} {m.group(2)}")
                if len(out) >= limit:
                    return out
    return out


def takeover_line(root):
    """[takeover] 接手面自检(2026-11-03):状态行/在途判据/死路径/断链"""
    import subprocess as _sp
    try:
        out = _sp.run([sys.executable, os.path.join(root, 'tools', 'sp_takeover_lint.py'), '--json'],
                      capture_output=True, text=True, timeout=120)
        d = json.loads(out.stdout)
    except Exception:
        return None
    return d


def contract_line(root):
    import subprocess as _sp
    try:
        out = _sp.run([sys.executable, os.path.join(root, 'tools', 'sp_schema_check.py'), '--json'],
                      capture_output=True, text=True, timeout=120)
        d = json.loads(out.stdout)
    except Exception:
        return None
    a = d.get('artifacts', {})
    def ok(k):
        v = a.get(k, {})
        return f"{list(v.get('schema', {}).keys())[0]}" if v.get('schema') else '-'
    return d.get('contract'), a.get('s1_meta', {}), a.get('ledger', {}), d.get('drift') or []


def verify_lint(root):
    import subprocess as _sp
    p = os.path.join(root, 'knowledge', 'assertions.md')
    if not os.path.exists(p):
        return {'total': 0, 'fail': []}
    txt = open(p, encoding='utf-8', errors='replace').read()
    cur, out = None, []
    for ln in txt.splitlines():
        m = asserts.NUM_RX.match(ln)
        if m:
            cur = 'A' + m.group(1)
        m2 = __import__('re').match(r'^verify:\s*`(.+)`\s*$', ln)
        if m2 and cur:
            out.append((cur, m2.group(1)))
    fails = []
    for aid, cmd in out:
        try:
            r = _sp.run(cmd, shell=True, capture_output=True, timeout=10, cwd=root)
            if r.returncode != 0:
                fails.append(aid)
        except Exception:
            fails.append(aid)
    return {'total': len(out), 'fail': fails}


def line_drift(root):
    """线页内容漂移：按 profile/line_sources.json 的声明，把线页状态字段与真源对齐。

    返回 [(line, expected, actual, why)]；配置缺失/无声明时返回 []。
    只做“声明过的线”，不猜所有线页的语义。
    """
    cfg_path = os.path.join(root, 'profile', 'line_sources.json')
    if not os.path.exists(cfg_path):
        return []
    try:
        cfg = json.load(open(cfg_path, encoding='utf-8'))
    except Exception:
        return []
    out = []
    for line, spec in cfg.items():
        if line.startswith('_') or not isinstance(spec, dict):
            continue
        lp = os.path.join(root, spec.get('file', ''))
        if not os.path.exists(lp):
            out.append((line, '线页存在', '缺失', 'line file missing'))
            continue
        text = open(lp, encoding='utf-8', errors='replace').read()
        m = re.search(spec.get('pattern', ''), text)
        actual = m.group(1) if m else None
        src = os.path.expanduser(spec.get('source', ''))
        if not os.path.exists(src):
            out.append((line, '真源存在', '缺失', f'source missing: {src}'))
            continue
        try:
            data = json.load(open(src, encoding='utf-8'))
            if spec.get('app'):
                data = (data.get('apps') or {}).get(spec['app'], {})
            expected = str(data.get(spec.get('field', ''), ''))
        except Exception as e:
            out.append((line, '真源可读', '读取失败', str(e)[:80]))
            continue
        if not actual:
            out.append((line, expected, '未匹配', 'line pattern not found'))
        elif actual != expected:
            out.append((line, expected, actual, 'version drift'))
        if spec.get('code_field') and spec.get('code_pattern'):
            mc = re.search(spec['code_pattern'], text)
            actual_c = mc.group(1) if mc else None
            expected_c = str(data.get(spec['code_field'], ''))
            if expected_c and actual_c != expected_c:
                out.append((line, f'vc{expected_c}', f'vc{actual_c or "未匹配"}', 'versionCode drift'))
    return out


def steward_line(root):
    """最近一轮 steward 是否有 traceback。

    2026-11-21：sp_convert 因 NameError 停摆 29 小时，steward 每一步都失败，
    但 `ssot_check` 只显示「健康」——失败只躺在 alerts/steward.log。
    """
    p = os.path.join(root, 'alerts', 'steward.log')
    try:
        lines = open(p, encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return None
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if 'steward run begin' in lines[i]:
            idx = i
            break
    if idx is None:
        return None
    tail = lines[idx:]
    tb = sum(1 for l in tail if l.startswith('Traceback (most recent call last)'))
    ts = tail[0].split('==')[0].strip() or '-'
    return {'ts': ts, 'tracebacks': tb, 'lines': len(tail)}


def tests_line(root):
    """最近一次全套回归 + 覆盖率基线（2026-11-22 立）。

    规模上来之后，「测试有没有跟上」必须能在体检单上看到，而不是靠人记得跑。
    数据源：tools/tests/.test-last.json（run_all 留痕）与 .coverage-last.json。
    """
    import json as _json
    t = os.path.join(root, 'tools', 'tests', '.test-last.json')
    c = os.path.join(root, 'tools', 'tests', '.coverage-last.json')
    out = {'total': 0, 'pass': 0, 'fail': 0, 'ts': '-', 'cov': None}
    try:
        d = _json.load(open(t, encoding='utf-8'))
        out.update(total=d.get('total', 0), **{'pass': d.get('pass', 0)},
                   fail=d.get('fail', 0), ts=(d.get('ts') or '')[:16].replace('T', ' '))
    except (OSError, ValueError):
        return None
    try:
        cov = _json.load(open(c, encoding='utf-8'))
        out['cov'] = cov.get('total_percent')
    except (OSError, ValueError):
        pass
    return out


def install_drift(root):
    """框架件漂移：实例 tools/ 与 kit 的 ssotlib 树 / 入口脚本对账。

    2026-11-23（批次 5 P0）：setup.sh/update.sh 曾只拷 ssotlib/*.py，
    v0.30 拆出的 ssotlib/index/ 子包安装后永久缺失——语义检索 ImportError。
    这里把「kit 有、实例无」变成体检单上的阻断项，不再靠人记得。
    """
    issues = {}
    kit = os.environ.get('SSOT_KIT') or os.path.expanduser('~/qoder_place/ssot-kit')
    tools = os.path.join(root, 'tools')
    # 必需子包：实例有 sp_semantic 就必须有 ssotlib/index
    if os.path.exists(os.path.join(tools, 'sp_semantic.py')):
        rel = 'tools/ssotlib/index/__init__.py'
        if not os.path.exists(os.path.join(root, rel)):
            issues[rel] = ('missing', '语义检索依赖的子包缺失')
    ktools = os.path.join(kit, 'tools')
    if os.path.isdir(os.path.join(ktools, 'ssotlib')):
        for dp, dns, fns in os.walk(os.path.join(ktools, 'ssotlib')):
            dns[:] = [d for d in dns if d != '__pycache__']
            for fn in fns:
                if not fn.endswith('.py'):
                    continue
                rel = os.path.relpath(os.path.join(dp, fn), kit)
                if not os.path.exists(os.path.join(root, rel)):
                    issues[rel] = ('missing', 'kit 有、实例无（先跑 update.sh）')
    for rel in ('tools/steward.sh', 'tools/session-gate.sh'):
        a = os.path.join(root, rel)
        b = os.path.join(kit, rel)
        if os.path.exists(a) and os.path.exists(b):
            try:
                if open(a, 'rb').read() != open(b, 'rb').read():
                    issues[rel] = ('stale', '内容与 kit 不一致（update.sh 不同步此文件）')
            except OSError:
                pass
    return [(rel, kind, why) for rel, (kind, why) in sorted(issues.items())]


def main():
    ap = cli.base_parser(epilog="【契约】意图：一次体检（台账/收件箱/索引/覆盖/接手面/契约）\n退出码：0=健康；1=有问题；2=参数错\n失败后：按 ❌ 行逐项处理\n\n示例:\n  ssot_check.py            # 六检查一屏;'== 完成(健康)' 为通过\n  ssot_check.py --json     # 机器可读", root=False)
    ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    ap.add_argument('--report', default=None, help='生成 SSOT_REPORT.md 的路径')
    ap.add_argument('--strict', action='store_true', help='断言重号/缺号或 inbox 积压时非零退出（值班/CI 用）')
    a = ap.parse_args()

    root = a.root
    print(f'== ssot_check · {root} ==')
    issues = 0

    # 1. 登记册
    reg = os.path.join(root, 'sessions', 'registry.md')
    reg_n, reg_last = 0, '(无条目)'
    if os.path.exists(reg):
        lines = [l for l in open(reg, encoding='utf-8') if l.startswith('- 2')]
        dates = re.findall(r'^- (\d{4}-\d{2}-\d{2})', '\n'.join(lines), re.M)
        reg_n = len(lines)
        reg_last = max(dates) if dates else '(无条目)'
        print(f'[registry] {reg_n} 条会话记录；最近活动 {reg_last}')
    else:
        print('[registry] ❌ 缺 sessions/registry.md'); issues += 1

    # 2. inbox + conf
    ib = inbox_stats(root)
    pending = pending_count(root)
    print(f"[inbox] 未提纯 {pending} 条" + ('（>20 条建议整理）' if pending > 20 else '') +
          f"；conf 覆盖 {ib['conf']}/{ib['total']}" +
          (f"；归一化 {ib['normalized']} 条" if ib['normalized'] else '') +
          (f"；非法值 {sorted(set(ib['bad']))}" if ib['bad'] else ''))

    # 2a. 标记单调守卫（A558：提纯只能追加，标记数不得回退）
    cur_m = marker_count(root)
    head_m = head_marker_count(root)
    if head_m is not None and cur_m < head_m:
        print(f"[inbox-guard] ❌ 标记数回退：{cur_m} < HEAD {head_m}（A558：先看 git diff，别 checkout）")
        issues += 1
    elif head_m is not None:
        print(f"[inbox-guard] 标记数 {cur_m}（HEAD {head_m}）")

    # 2b. 捕获层（S1，2026-10-28）
    st_n, st_today, alive_min, last_line = capture_stats(root)
    alive_s = '缺失' if alive_min is None else (f'{alive_min} 分钟前' if alive_min < 120 else f'{alive_min // 60} 小时前')
    print(f"[capture] staging {st_n} 条 / 今日 +{st_today} / 存活 {alive_s}")
    if last_line:
        print(f"[capture] 上轮:{last_line.split(' ', 1)[-1]}")

    # 2c. 语义常驻（M2，2026-10-29）
    p50, p90, n, fb = semantic_stats(root)
    if n:
        print(f"[semantic] p50 {p50}ms · p90 {p90}ms · 样本 {n} · 今日 fallback {fb}")
    else:
        print("[semantic] 无常驻 daemon 样本（走一次性路径）")
    idle = semantic_idle_stats(root)
    c24, c7 = idle['24h'], idle['7d']
    idle_s = '未知' if idle['idle_min'] is None else f"{idle['idle_min']}m"
    wake_s = 'n/a' if c24['wake_success_pct'] is None else f"{c24['wake_success_pct']}%"
    cold_s = 'n/a' if c24['cold_p95_s'] is None else f"{c24['cold_p95_s']}s"
    print(f"[semantic-idle] 24h cold={c24['cold_acquire']} wake={wake_s} "
          f"cold_p95={cold_s} ready={c24['ready']} reaped={c24['reaped']} "
          f"manual={c24.get('manual_reaped', 0)} "
          f"skip_active={c24['skip_active']} skip_race={c24['skip_race']} "
          f"failed={c24['term_failed'] + c24['state_invalid']} · 7d cold={c7['cold_acquire']} "
          f"reaped={c7['reaped']} · state={idle['state']} idle={idle_s} · last={idle['last'] or 'none'}")

    # 2d. 消费端（Phase B，2026-10-31）
    d7, dmin = dispatch_stats(root)
    d_age = '从未' if dmin is None else (f'{dmin} 分钟前' if dmin < 120 else f'{dmin // 60} 小时前')
    warn = '' if d7 >= 20 else '（健康目标 20 次/周；当前偏低，属提示非告警）'
    print(f"[dispatch] 7 天内 {d7} 次 · 最近 {d_age}{warn}")
    nc, nt = citation_stats(root)
    if nt:
        print(f"[cite] 断言被引用 {nc}/{nt}（{nc * 100 // nt}%）")

    # 2e. 覆盖审计（2026-10-31）
    cov_note = ''
    cv = coverage_line(root)
    if cv:
        idx_n, human_n, miss_n, tool_n, unresolved, skipped_n = cv
        print(f"[coverage] 人类源 {idx_n}/{human_n} 会话 · 未接入 {miss_n}"
              + (f" · 策略跳过 {skipped_n}" if skipped_n else '')
              + (f" · tool 源跳过 {tool_n}" if tool_n else ''))
        if unresolved > 0:
            cov_note = f"覆盖缺口 {unresolved}"

    # 2e2. S0 归档敏感性（2026-11-18）
    archive_note = ''
    ar = archive_line(root)
    if ar:
        by = ar.get('by_confidence') or {}
        hit = int(ar.get('high_files', ar.get('files_hit') or 0))
        pol = ar.get('_policy') or {}
        ptxt = ''
        if pol:
            ptxt = (f" · policy={pol.get('sensitivity', 'high')}"
                    f"/scrub={'on' if pol.get('scrub_default') else 'off'}")
        extra = ''
        if by:
            extra = (f" · high {by.get('high', 0)} / medium {by.get('medium', 0)}"
                     f" / low {by.get('low', 0)}（low 只报告）")
        print(f"[archive] S0 密钥 high {hit}/{ar.get('scanned', 0)} 文件"
              f" · {by.get('high', ar.get('matches', 0))} 处" + extra + ptxt
              + (" · 见 alerts/s0-scan.json" if hit else ''))
        if hit:
            archive_note = f"S0 密钥 {hit} 文件"

    # 2h. 断言 verify 字段(2026-11-04)
    vl = verify_lint(root)
    print(f"[verify] 可执行断言 {vl['total']} 条" + (f" · 失败 {vl['fail']}" if vl['fail'] else " · 全过"))
    # 2g. 数据契约(2026-11-04)
    cv = contract_line(root)
    if cv:
        ver, s1, led, drift = cv
        print(f"[contract] 实例 v{ver} · s1 schema {s1.get('schema')} · 账本 schema {led.get('schema')}"
              + (f" · ⚠ 漂移 {len(drift)}" if drift else " · 一致"))
    # 2f. 接手面自检(2026-11-03)
    tk = takeover_line(root)
    if tk:
        ex = dead_path_examples(tk)
        print(f"[takeover] {tk['pages']} 页 · 状态行 {tk['status_ok']} · 在途 {tk['todo']}(判据+owner {tk['todo_with_criteria']})"
              f" · 死路径 {tk['dead_paths']}(建议) · 断链 {tk['broken_links']}"
              + (f" · 例: {'；'.join(ex)}" if ex else ''))

    # 3. 线页
    ldir = os.path.join(root, 'lines')
    stale = []
    line_n = 0
    if os.path.isdir(ldir):
        now = datetime.datetime.now()
        for fn in os.listdir(ldir):
            if not fn.endswith('.md') or fn.startswith('_'):
                continue
            line_n += 1
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(ldir, fn)))
            if (now - mt).days > 30:
                stale.append(f'{fn}({(now - mt).days}d)')
    print(f'[lines] {line_n} 条线' + (f'；⚠️ 过期: {", ".join(stale)}' if stale else '；全部新鲜'))
    if os.path.exists(os.path.join(root, 'profile', 'line_sources.json')):
        drifts = line_drift(root)
        if drifts:
            for line, exp, act, why in drifts:
                print(f'[line-drift] ❌ {line}: 线页 {act} ≠ 真源 {exp}（{why}）')
            issues += len(drifts)
        else:
            print('[line-drift] 声明过的线页与真源一致')

    # 4. 记忆薄壳
    mem = os.path.expanduser('~/.qoder/memory/MEMORY.md')
    mem_b = 0
    if os.path.exists(mem):
        mem_b = os.path.getsize(mem)
        flag = f'⚠️ >{MEM_WARN}B，需瘦身' if mem_b > MEM_WARN else '健康'
        print(f'[memload] MEMORY.md {mem_b:,}B（{flag}）')
        if mem_b > MEM_WARN:
            issues += 1

    # 4b. 值守最近一轮是否带 traceback（失败不能只躺在 alerts/steward.log）
    sw = steward_line(root)
    if sw:
        if sw['tracebacks']:
            print(f"[steward] ❌ 最近一轮 {sw['ts']}：{sw['tracebacks']} 处 traceback（入口失败会静默）")
            issues += 1
        else:
            print(f"[steward] 最近一轮 {sw['ts']} · 无 traceback")

    # 4c. 回归测试最近一次结果（nightly 写，体检单读）
    tl = tests_line(root)
    if tl:
        cov = f" · 覆盖 {tl['cov']}%" if tl.get('cov') is not None else ''
        if tl['fail']:
            print(f"[tests] ❌ {tl['pass']}/{tl['total']} · 最近 {tl['ts']}{cov}")
            issues += 1
        else:
            print(f"[tests] {tl['pass']}/{tl['total']} 全绿 · 最近 {tl['ts']}{cov}")

    # 5. 断言 lint（只报不改号）
    al = assertion_lint(root)
    if al.get('total'):
        print(f"[assertions] {al['total']} 条；最新 A{al['latest']}；"
              f"重复 {al['dups']}（{fmt_ids(al['dup_ids'])}）；"
              f"缺号 {al['missing']}（{fmt_ids(al['missing_ids'])}）；标签 {al['tags']}")
    else:
        print('[assertions] 无断言文件或为空')

    # 6. build commit / 索引
    build_path, build = find_build(root)
    head = git(root, 'rev-parse', '--short', 'HEAD')
    lag = ''
    if build_path:
        bc = build.get('commit', '-')
        if bc and bc != '-' and head and bc != head:
            n = git(root, 'rev-list', '--count', f'{bc}..HEAD')
            lag = f'落后 {n} commits' if n else 'commit 不同'
        cfg = build.get('config') or {}
        tp = build.get('throughput_chunks_per_s')
        extra = ''
        if cfg:
            extra += f" · batch {cfg.get('batch', '?')}/workers {cfg.get('workers', '?')}"
        if tp:
            extra += f" · {tp} 块/秒"
        print(f"[build] {os.path.relpath(build_path, root)} · commit {bc} · "
              f"{build.get('chunks', '?')} 块 · {build.get('built_at', '?')}{extra}" +
              (f'（{lag}）' if lag else ''))
    else:
        print('[build] 无 BUILD.json（索引尚未记录 built_at_commit）')

    # 8. 安装漂移（2026-11-23 · P0：子包漏装）
    drift = install_drift(root)
    blocking = [x for x in drift if x[1] != 'stale']
    stale_items = [x for x in drift if x[1] == 'stale']
    if blocking:
        print(f"[install-drift] ❌ {len(blocking)} 项框架文件缺失（先跑 update.sh）：")
        for rel, kind, why in blocking[:10]:
            print(f"  - {rel}（{why}）")
        if len(blocking) > 10:
            print(f"  … 其余 {len(blocking) - 10} 项")
        issues += 1
    for rel, kind, why in stale_items[:5]:
        print(f"[install-drift] ⚠ {rel}：{why}（本地定制可忽略；由 install-steward.sh 管理）")
    if not drift:
        print("[install-drift] 框架文件完整")

    # 注意：这里的变量不要复用上面的 pending（那是未提纯条数 int）——2026-11-22 修
    pend_idx = pending_line(root)
    if pend_idx:
        print(f"[pending-index] {pend_idx.get('sessions', 0)} 会话 / ~{pend_idx.get('est_blocks', 0)} 块"
              f" · since {pend_idx.get('created_at', '-')}"
              + (f" · 已索引待压实" if pend_idx.get('pack_stale') else ""))

    # 7. 草稿/未尽/演练
    drafts = len(glob.glob(os.path.join(root, 'sessions', '_pending', '*.md')))
    loops = 0
    lp = os.path.join(root, 'knowledge', 'open-loops.md')
    if os.path.exists(lp):
        loops = sum(1 for l in open(lp, errors='replace') if l.startswith('- '))
    drills = sorted(glob.glob(os.path.join(root, 'alerts', 'drills', '*.md')))
    drill = os.path.basename(drills[-1]) if drills else '-'
    print(f'[pending] 草稿 {drafts}；[open-loops] {loops}；[drill] {drill}')

    # 完成态汇总：阻断项 + 非阻断提示（2026-11-18：原先只报 issues，死路径/覆盖缺口看不见）
    notes = []
    if cov_note:
        notes.append(cov_note)
    if archive_note:
        notes.append(archive_note)
    if tk and tk.get('dead_paths'):
        notes.append(f"死路径 {tk['dead_paths']}")
    if lag and lag.startswith('落后'):
        notes.append(f"索引{lag}")
    if drafts:
        notes.append(f"草稿 {drafts}")
    if pend_idx:
        notes.append(f"待索引 {pend_idx.get('sessions', 0)} 会话")
    tail = f"{issues} 项需处理" if issues else "健康"
    if notes:
        tail += "；提示 " + "、".join(notes)
    print(f'== 完成 ==（{tail}）')

    if a.report:
        now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        bc = build.get('commit', '-') if build else '-'
        out = [
            f'# SSOT_REPORT · {datetime.date.today().isoformat()}',
            '',
            f'> 正本 commit {head or "-"} · 生成 {now}',
            '',
            f'- 线：{line_n} 条' + (f'；过期：{", ".join(stale)}' if stale else ''),
            f'- 登记：{reg_n} 条；最近 {reg_last}',
            f"- inbox：{pending} 条未提纯；conf 覆盖 {ib['conf']}/{ib['total']}",
            (f"- 断言：{al['total']} 条；最新 A{al['latest']}；"
             f"重复 {al['dups']}（{fmt_ids(al['dup_ids'])}）；"
             f"缺号 {al['missing']}（{fmt_ids(al['missing_ids'])}）；标签 {al['tags']}") if al.get('total') else '- 断言：无',
            f'- 未尽：{loops} 条；草稿：{drafts} 条',
            f"- 索引：{os.path.relpath(build_path, root) if build_path else '无'} · "
            f"commit {bc} · {build.get('chunks', '?')} 块 · {build.get('built_at', '?')}" +
            (f'（{lag}）' if lag else ''),
            f'- 最近演练：{drill}',
        ]
        os.makedirs(os.path.dirname(a.report) or '.', exist_ok=True)
        with open(a.report, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out) + '\n')
        print(f'✅ 报告 → {a.report}')

    # --strict：给 CI / 值班用——断言重号/缺号或 inbox 积压即非零退出（默认只报不拦）
    if a.strict:
        blocking = []
        if al.get('dups'):
            blocking.append(f"断言重号 {al['dups']}")
        if al.get('missing'):
            blocking.append(f"断言缺号 {al['missing']}")
        if pending > 20:
            blocking.append(f"inbox 未提纯 {pending}（>20 需整理）")
        drifts = line_drift(root)
        if drifts:
            blocking.append(f"线页漂移 {len(drifts)} 条")
        if blocking:
            print('❌ strict 未过：' + '；'.join(blocking))
            sys.exit(1)
        print('✅ strict 通过')
    sys.exit(0)


if __name__ == '__main__':
    main()

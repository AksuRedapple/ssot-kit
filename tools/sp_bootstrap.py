#!/usr/bin/env python3
"""sp_bootstrap · 全量 dump 编排:发现 → 转换 → 向量化 → 捕获 → 知识抽取 → 审阅表

设计:drafts/full-dump-design-2026-10-31.md §5.5
原则:每阶段幂等、可单独跑、失败即停;状态落 ~/.ssot/bootstrap-state.json

用法:
  sp_bootstrap.py --plan                          # 只读:每阶段会做什么、耗时/磁盘估计
  sp_bootstrap.py --full-dump --dry-run           # 打印将要执行的命令
  sp_bootstrap.py --full-dump --allow-capture --allow-llm
  sp_bootstrap.py --resume                        # 从最后未完成阶段继续
  sp_bootstrap.py --only index                    # 单阶段重跑
"""
import argparse, glob, json, os, subprocess, sys, time

SSOT = os.path.expanduser('~/ssot')
STATE = os.environ.get('ZB_BOOTSTRAP_STATE') or os.path.expanduser('~/.ssot/bootstrap-state.json')


def _capture_available():
    """The public kit omits content-capture extensions; enable them as a pair."""
    return all(os.path.isfile(os.path.join(SSOT, 'tools', name))
               for name in ('sp_sweep.py', 'sp_capture.py'))


CAPTURE_AVAILABLE = _capture_available()
PHASES = ['discover', 'convert', 'index'] + (['capture'] if CAPTURE_AVAILABLE else []) + ['extract', 'triage']


def sh(cmd, dry=False, timeout=7200):
    print('  $ ' + ' '.join(cmd))
    if dry:
        return 0
    r = subprocess.run(cmd, cwd=SSOT, timeout=timeout)
    return r.returncode


def load_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {'phases': {}, 'started': None}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    json.dump(st, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def coverage():
    r = subprocess.run([sys.executable, os.path.join(SSOT, 'tools', 'sp_coverage.py'), '--json'],
                       capture_output=True, text=True, cwd=SSOT, timeout=300)
    return json.loads(r.stdout)


def plan():
    d = coverage()
    rows, pending = d.get('sources', []), d.get('pending', [])
    human = [r for r in rows if r['src'] != 'codex']
    todo_convert = sum(max(0, r['raw'] - r['s1']) for r in human)
    todo_index = sum(max(0, r['s1'] - r['empty'] - r['covered']) for r in human)
    sessions = sum(r['s1'] for r in human)
    print('▸ 全量 dump 计划（只读,不写盘）')
    print(f'  会话: 已转 {sessions} · 待转 {todo_convert} · 待建库 {todo_index} 会话')
    print(f"  tool 源跳过: {sum(p['raw'] for p in pending if p['src'] == 'codex')} (codex)")
    print('\n  阶段              动作                                   预计')
    print('  discover          统计每源原始/S1/索引缺口               <10s')
    print(f'  convert           sp_convert --src <源>(仅缺的源)        {max(1, todo_convert // 5)} 分钟')
    print(f'  index             sp_index --incremental                 {"~6 分钟/千块" if todo_index else "无需重建"}')
    if CAPTURE_AVAILABLE:
        print(f'  capture           sp_sweep（需 --allow-capture）           {max(1, sessions // 40)} 分钟')
    print(f'  extract           sp_llm_extract（需 --allow-llm）          约 {sessions} 次调用/小时级')
    print('  triage            sp_triage extract → 审阅表             1 分钟')
    print('\n  提示: 先跑 --full-dump --dry-run 看命令;capture/extract 需显式开关。')


def run_phase(ph, dry=False, allow_capture=False, allow_llm=False, limit=0):
    if ph == 'discover':
        d = coverage()
        print(f"  发现: {len(d['sources'])} 源 / {sum(r['s1'] for r in d['sources'])} 会话已转")
        return 0
    if ph == 'convert':
        rc = 0
        for src in ('qoder', 'cc', 'dsh', 'pi', 'opencode'):
            if src == 'opencode':
                rc |= sh([sys.executable, 'tools/sp_opencode.py', '--limit', '200'], dry)
            else:
                rc |= sh([sys.executable, 'tools/sp_convert.py', '--src', src], dry)
        return rc
    if ph == 'index':
        return sh([sys.executable, 'tools/sp_index.py', '--incremental'], dry, timeout=14400)
    if ph == 'capture':
        if not CAPTURE_AVAILABLE:
            print('  ⏭  capture 不在当前发行子集中'); return 0
        if not allow_capture:
            print('  ⏭  capture 跳过（需 --allow-capture）'); return 0
        return sh([sys.executable, 'tools/sp_sweep.py', '--quota', '24'], dry)
    if ph == 'extract':
        if not allow_llm:
            print('  ⏭  extract 跳过（需 --allow-llm）'); return 0
        import concurrent.futures as _cf
        sids = _all_human_sids()
        done = _complete_sessions()
        todo = [x for x in sids if x not in done]
        if limit:
            todo = todo[:limit]
        print(f'  待抽 {len(todo)} 个会话（已完成 {len(done)}）')
        if dry:
            for sid in todo[:5]:
                print(f'  $ sp_llm_extract.py --sid {sid} --max-chunks 3 --to-ledger')
            if len(todo) > 5:
                print(f'  … 其余 {len(todo) - 5} 个')
            return 0
        fails = 0

        def one(sid):
            r = subprocess.run([sys.executable, 'tools/sp_llm_extract.py', '--sid', sid,
                                '--max-chunks', '8', '--stop-ratio', '0.6', '--to-ledger'], cwd=SSOT,
                               capture_output=True, text=True, timeout=3600)
            return sid, r.returncode

        with _cf.ThreadPoolExecutor(max_workers=3) as ex:
            for sid, rc in ex.map(one, todo):
                if rc != 0:
                    fails += 1; print(f'  ✗ {sid} rc={rc}')
        print(f'  extract 完成:成功 {len(todo) - fails}/{len(todo)}')
        print('  → 批次末尾统一撞正本（一次全量,而不是每会话一次）')
        subprocess.run([sys.executable, 'tools/sp_candidates.py', '--against-assertions'], cwd=SSOT)
        return 0 if fails == 0 else 1
    if ph == 'triage':
        d = coverage()
        rc = 0
        for sid in _session_ids(d)[:20]:
            rc |= sh([sys.executable, 'tools/sp_triage.py', 'extract', '--sid', sid], dry)
        return rc
    return 1


def _complete_sessions(chunk_rows=200):
    """只有"块数跑满"的会话才算完成;半成品要继续(逐块落盘后的续抽)"""
    import math
    done = set()
    for f in glob.glob(os.path.join(SSOT, 'compile', 'llm-extract', '*.jsonl')):
        sid = os.path.basename(f)[:-6]
        got = set()
        clog = f[:-6] + '.chunks'
        if os.path.exists(clog):
            got = {int(x) for x in open(clog, encoding='utf-8').read().split() if x.strip().isdigit()}
        for ln in open(f, encoding='utf-8', errors='replace'):
            try:
                got.add(json.loads(ln).get('chunk'))
            except Exception:
                pass
        tot = f[:-6] + '.total'
        if os.path.exists(tot):
            need = int(open(tot, encoding='utf-8').read().strip() or 1)
        elif not os.path.exists(clog):
            need = 1
        else:
            rows = 0
            for d in glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', f'*{sid}*', 'transcript.jsonl')):
                rows = sum(1 for _ in open(d, encoding='utf-8', errors='replace'))
                break
            need = max(1, min(math.ceil(rows / chunk_rows), 3))
        if got and max(x for x in got if isinstance(x, int)) >= need:
            done.add(sid)
    return done


def _all_human_sids():
    """扫 S1-sessions(qoder/cc/dsh/pi/opencode 的人类会话),排除 codex(tool)与空壳"""
    import glob as _g
    out = []
    for d in _g.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*')):
        src = d.split('/evidence/')[1].split('/')[0]
        if src == 'codex':
            continue
        tr = os.path.join(d, 'transcript.jsonl')
        if not os.path.exists(tr) or os.path.getsize(tr) < 2048:
            continue
        parts = os.path.basename(d).split('-')
        sid = parts[3] if len(parts) > 3 and len(parts[3]) == 8 else None
        if sid:
            out.append(sid)
    return out


def _session_ids(d):
    out = []
    for r in d.get('sources', []):
        if r['src'] == 'codex':
            continue
        out.extend(r.get('sids', []) or [])
    return out


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_bootstrap.py --plan\n  sp_bootstrap.py --full-dump --dry-run\n  sp_bootstrap.py --full-dump --allow-llm --resume',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--full-dump', action='store_true')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--only', choices=PHASES)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--allow-capture', action='store_true')
    ap.add_argument('--allow-llm', action='store_true')
    ap.add_argument('--limit', type=int, default=0, help='每阶段最多处理 N 个(0=不限)')
    a = ap.parse_args()

    if a.plan:
        plan(); return 0
    if not (a.full_dump or a.resume or a.only):
        ap.print_help(); return 1

    st = load_state()
    todo = [a.only] if a.only else PHASES
    if a.resume and not a.only:
        done = {k for k, v in st['phases'].items() if v.get('status') == 'ok'}
        todo = [p for p in PHASES if p not in done]
        print(f'▸ resume: 跳过已完成 {sorted(done) or "（无）"}')
    st['started'] = st.get('started') or time.strftime('%FT%T%z')
    print(f'▸ 执行阶段: {todo}' + (' [dry-run]' if a.dry_run else ''))
    for ph in todo:
        t0 = time.time()
        print(f'── {ph}')
        try:
            rc = run_phase(ph, a.dry_run, a.allow_capture, a.allow_llm, a.limit)
        except Exception as e:  # noqa: BLE001
            rc = 1; print(f'  ❌ {ph} 异常: {e}')
        st['phases'][ph] = {'status': 'ok' if rc == 0 else 'fail', 'ts': time.strftime('%FT%T%z'),
                            'seconds': int(time.time() - t0)}
        if not a.dry_run:
            save_state(st)
        if rc != 0:
            print(f'❌ 停在 {ph}（后续阶段未执行）')
            return 1
    if not a.dry_run:
        st['finished'] = time.strftime('%FT%T%z'); save_state(st)
    print('✅ 全部阶段完成')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

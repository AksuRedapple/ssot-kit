#!/usr/bin/env python3
"""sp_handoff · 对话转生四段模板的生成与验收(v0.1)
用法:
  python3 sp_handoff.py --init [--goal "..."] [--fact "..." ...] [--reject "..." ...] [--next "..."]
  python3 sp_handoff.py --check            # 验收四段/出处/否决段
落盘: ./.memory/handoff/latest.md(工作区级)
"""
import argparse, os, sys, datetime, re

TPL = """# handoff · {name} · {ts}

## 1 目标
{goal}

## 2 已确认事实(带出处)
{facts}

## 3 否决过的路(最容易丢,必须写)
{rejects}

## 4 下一步 / 未闭合
{nexts}
"""


def path():
    """从 cwd 向上找 .memory/handoff/latest.md(便于在子目录里也能 --check)"""
    d = os.getcwd()
    while True:
        p = os.path.join(d, '.memory', 'handoff', 'latest.md')
        if os.path.exists(p):
            return p
        nd = os.path.dirname(d)
        if nd == d:
            return os.path.join(os.getcwd(), '.memory', 'handoff', 'latest.md')
        d = nd


def _preset(name):
    """加载并校验 preset;引用失效就在这里报错(不静默)"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sp_presets as P
    errs = P.validate(name)
    if errs:
        sys.exit('❌ preset 引用失效:\n  - ' + '\n  - '.join(errs))
    return P, P.load()[name]


def init(a):
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    name = os.path.basename(os.getcwd()) or 'workspace'
    facts = '\n'.join(f'- {x} | source: 待补' for x in a.fact) or '- <结论> | source: <会话#行 / 命令输出>'
    rejects = '\n'.join(f'- ❌ {x} —— 否决原因:待补' for x in a.reject) or '- ❌ <方案> —— 否决原因:<为什么不行>'
    nexts = '\n'.join(f'- ⏳ {x}' for x in a.next) or '- ⏳ <下一步>(判据:<怎么算完成>)\n- ❓ <悬而未决>'
    if getattr(a, 'preset', None):
        P, cfg = _preset(a.preset)
        ref, _, _ = P.brief(a.preset)
        facts = facts + '\n- 本摊 preset:' + a.preset + '（' + cfg.get('desc', '') + '）'
        nexts = ('- ⏳ 先读 preset 指定的主线页与断言:' + (cfg.get('line') or '(无)') + '\n' + nexts)
        print('preset 校验通过:\n' + ref)
    open(p, 'w', encoding='utf-8').write(TPL.format(
        name=name, ts=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        goal=a.goal or '<一句话:做完什么算完>', facts=facts, rejects=rejects, nexts=nexts))
    print(f'✅ 已写 {p}')
    _triage_hook()


def _triage_hook():
    """收尾钩子(2026-10-31):手写完后自动抽候选,只打印提示,**不自动 accept**。
    失败一律不阻断(硬约束 3)。可用 ZB_SKIP_TRIAGE=1 关闭。"""
    if os.environ.get('ZB_SKIP_TRIAGE') == '1':
        return
    try:
        import glob as _g
        import subprocess as _sp
        sid = (os.environ.get('DSH_SESSION_ID') or os.environ.get('CLAUDE_SESSION_ID')
               or os.environ.get('ZB_SESSION_ID') or '')[:8]
        if not sid or not sid.isalnum():
            cands = sorted(_g.glob(os.path.expanduser('~/ssot/evidence/*/S1-sessions/*')),
                           key=lambda d: os.path.getmtime(d), reverse=True)
            if cands:
                parts = os.path.basename(cands[0]).split('-')
                sid = parts[3] if len(parts) > 3 else ''
        if not sid:
            print('  （收尾候选:未识别到会话号,可手动跑 sp_triage.py extract --sid <8位>）')
            return
        r = _sp.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sp_triage.py'),
                     'extract', '--sid', sid], capture_output=True, text=True, timeout=120)
        out = (r.stdout or '').strip().splitlines()
        n = next((l for l in out if l.startswith('候选 ')), '')
        print(f'  {n or "候选 0 条"}(收尾钩子:sid={sid})')
        if n and not n.startswith('候选 0'):
            print(f'  → sp_triage.py accept --sid {sid} --ids 1,2,3 --line <线名>')
    except Exception as e:  # noqa: BLE001
        print(f'  （收尾候选跳过:{type(e).__name__}）')


def check(a=None):
    p = path()
    if not os.path.exists(p):
        sys.exit(f'❌ 没有 handoff:{p}')
    txt = open(p, encoding='utf-8').read()
    secs = re.findall(r'^## (\d) ', txt, re.M)
    ok = True
    print(f'四段:{len(secs)} 段 {"✅" if len(secs) == 4 else "❌"}')
    ok &= len(secs) == 4
    body2 = re.search(r'## 2 .*?(?=\n## 3|$)', txt, re.S)
    n_src = len(re.findall(r'source:', body2.group(0))) if body2 else 0
    print(f'事实带出处:{n_src} 条 {"✅" if n_src >= 1 else "❌"}')
    ok &= n_src >= 1
    body3 = re.search(r'## 3 .*?(?=\n## 4|$)', txt, re.S)
    n_rej = len(re.findall(r'❌', body3.group(0))) if body3 else 0
    print(f'否决段:{n_rej} 条 {"✅" if n_rej >= 1 else "❌"}')
    ok &= n_rej >= 1
    if a is not None and getattr(a, 'preset', None):
        P, cfg = _preset(a.preset)
        ref, _na, _nol = P.brief(a.preset)
        print('  ' + ref.replace(chr(10), ' · '))
    print('结果:' + ('✅ 通过' if ok else '❌ 不合格'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(
    epilog='示例:\n  sp_handoff.py --init --goal "做完 X" --fact "Y 已验证|source: 会话#L12" --reject "方案 Z|原因: 代价太高" --next "接 dispatch 注入"\n  sp_handoff.py --check     # 四段齐 / 事实带 source / 否决段 >= 1\n\n落到 ./.memory/handoff/latest.md;dispatch --level pointer 会自动注入前 8 行。\n唯一真判据:新会话不看旧会话,也能说出「否决过的路」且不重走。',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--init', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--preset', default=None, help='转生 preset(index-work/infra-ops/writing/generic)')
    ap.add_argument('--goal', default='')
    ap.add_argument('--fact', action='append', default=[])
    ap.add_argument('--reject', action='append', default=[])
    ap.add_argument('--next', action='append', default=[])
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a))
    if a.init:
        return init(a)
    ap.print_help()


if __name__ == '__main__':
    main()

import datetime, sys
#!/usr/bin/env python3
"""sp_dispatch · 按预算分级注入(v0.1 · 2026-10-25)

替代"每次开局把所有指针硬塞进上下文"的做法:默认只给**指针**,摘要按预算截,
全文只在被问到/显式 --level full 时拉。

三级:
  pointer  → 能力行 + 命中线页标题/状态 + open-loops 前 3(≈120–200 tok)
  summary  → 再加「当前状态」「关键判据·数字」段落(默认 ≤700 tok)
  full     → 整页(仍受 --budget 约束,超出显式标注截断)

用法:
  python3 sp_dispatch.py --for dsh --cwd ~/ssot                  # pointer
  python3 sp_dispatch.py --level summary --budget 900
  python3 sp_dispatch.py --level full --line ssot-hub --budget 4000
"""
import argparse, json, os, re
from pathlib import Path

SSOT = os.path.expanduser('~/ssot')
# 各 harness 的默认注入预算(可用 --budget 覆盖)
HARNESS_BUDGET = {'dsh': 700, 'cc': 600, 'codex': 500, 'pi': 500, 'opencode': 500}
BUILD = os.path.join(SSOT, 'S2-index', 'semantic', 'BUILD.json')


def tok(s):
    """粗估:中文 1 字≈1 tok,英文 4 字符≈1 tok;取保守折算"""
    cjk = len(re.findall(r'[\u4e00-\u9fff]', s))
    other = len(s) - cjk
    return int(cjk + other / 3.2)


def capability_line():
    try:
        d = json.load(open(BUILD))
        n = int(d.get('chunks') or 0)
        ts = (d.get('built_at') or '')[:16].replace('T', ' ')
        if n > 0:
            return f"语义检索:可用({n:,} 块 · 建于 {ts})"
        return "语义检索:**当前不可用**(chunks=0,索引重建中)——找旧事先用 grep/S1 原文"
    except Exception:
        return "语义检索:**当前不可用**(无 BUILD.json)"


def line_pages():
    out = []
    for p in sorted(os.listdir(os.path.join(SSOT, 'lines'))):
        if not p.endswith('.md') or p.startswith('_'):
            continue
        path = os.path.join(SSOT, 'lines', p)
        txt = open(path, encoding='utf-8', errors='replace').read()
        head = txt[:600]
        title = re.search(r'^#\s*线[：:]\s*(.+)$', txt, re.M)
        st = re.search(r'状态[:：]\s*([^—|]+)', head)
        rc = re.search(r'最近[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', head)
        sc = re.search(r'现场[:：]\s*(.+)$', head, re.M)
        out.append({
            'slug': p[:-3],
            'title': (title.group(1).strip() if title else p[:-3]),
            'status': (st.group(1).strip() if st else ''),
            'recent': (rc.group(1) if rc else ''),
            'scene': (sc.group(1).strip() if sc else ''),
            'text': txt,
        })
    return out


def match(pages, cwd):
    if not cwd:
        return []
    if cwd.rstrip('/') == os.path.expanduser('~').rstrip('/'):
        return [p for p in pages if p['slug'] == 'ssot-hub']
    cwd = cwd.rstrip('/')
    hit = []
    for p in pages:
        sc = p['scene']
        if not sc:
            continue
        for m in re.findall(r'`([^`]+)`', sc):
            m = os.path.expanduser(m)
            q = m.rstrip('/')
            if q and (cwd == q or cwd.startswith(q + '/') or q.startswith(cwd + '/')):
                hit.append(p)
                break
    if not hit:
        return [p for p in pages if p['slug'] == 'ssot-hub']
    # 取"最具体"的匹配:现场路径最长者为最优;同长度最多 2 条
    def depth(pg):
        return max([len(os.path.expanduser(m)) for m in re.findall(r'`([^`]+)`', pg['scene'] or '')] or [0])
    hit.sort(key=depth, reverse=True)
    best = depth(hit[0])
    return [pg for pg in hit if depth(pg) >= best][:2]


def section(page_text, name):
    m = re.search(r'^##\s*' + re.escape(name) + r'.*?$(.*?)(?=^##\s|\Z)', page_text, re.M | re.S)
    return (m.group(1).strip() if m else '')


def open_loops(n=3):
    """只取 A 档里**在推**的条目(跳过 ✅/⛔/📌 归档符号),避免指针被历史条目撑胖"""
    p = os.path.join(SSOT, 'knowledge', 'open-loops.md')
    if not os.path.exists(p):
        return []
    out, inA = [], False
    for ln in open(p, encoding='utf-8', errors='replace'):
        t = ln.strip()
        if t.startswith('## A'):
            inA = True
            continue
        if t.startswith('## '):
            inA = False
            continue
        if inA and t.startswith('-') and not t[1:].strip().startswith(('✅', '⛔', '📌')):
            out.append(t)
    return out[:n]


def _find_handoff():
    d = os.getcwd()
    while True:
        p = os.path.join(d, '.memory', 'handoff', 'latest.md')
        if os.path.exists(p):
            return p
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def handoff_block(max_lines=8):
    for p in (_find_handoff(),):
        if p and os.path.exists(p):
            L = open(p, encoding='utf-8', errors='replace').read().splitlines()[:max_lines]
            return '\n'.join((x[:110] + '…') if len(x) > 110 else x for x in L)
    return ''


LOG = os.path.join(SSOT, 'logs', 'dispatch.log')


def log_use(level, budget, tokens, lines, preset=None, harness='dsh'):
    """每次 dispatch 记一行(2026-10-31 Phase B):没有日志,"开工注入"就无法被验证"""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                'level': level, 'budget': budget, 'tokens': tokens,
                'lines': lines, 'preset': preset, 'harness': harness,
                'cwd': os.getcwd(),
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass


def render(level, pages, budget):
    parts = []
    parts.append(f"- 能力:{capability_line()}")
    # L4 观测：SSOT 使用率（2026-10-29）。让"没查"变成可见指标。
    try:
        import json as _json, subprocess as _sp
        _r = _sp.run(['python3', str(Path.home()/'ssot/tools/sp_adherence.py'), '--days', '7', '--json'],
                     capture_output=True, text=True, timeout=25)
        if _r.returncode == 0 and _r.stdout.strip():
            _d = _json.loads(_r.stdout)
            _n = _d.get('nudges') or {}
            parts.append(f"- 记忆使用(7天):语义检索 {_d.get('usage',0)} 次｜提示 boot {_n.get('boot',0)}/gate {_n.get('gate',0)}/periodic {_n.get('periodic',0)}")
    except Exception:
        pass
    for pg in pages[:2]:
        parts.append(f"- 线:{pg['title']}({pg['status']},最近 {pg['recent']})→ `lines/{pg['slug']}.md`")
    if level == 'pointer':
        loops = open_loops(3)
        if loops:
            parts.append('- 未尽事项:')
            parts += ['  ' + re.sub(r'^-\s*', '· ', l)[:90] for l in loops]
        ho = handoff_block()
        if ho:
            parts.append('- 上一摊 handoff(截断):\n' + ho)
        out = '\n'.join(parts)
        if tok(out) > budget:
            # 依次丢弃可选块(从尾部往前):handoff → 未尽事项,直到进预算
            cur = parts[:]
            for i in range(len(cur) - 1, -1, -1):
                if tok('\n'.join(cur)) <= budget:
                    break
                cur = cur[:i] + cur[i + 1:]
            out = '\n'.join(cur)
            if tok(out) > budget:      # 仍超:硬截(**给标记留 15 tok**)
                while tok(out) > max(60, budget - 15) and len(out) > 120:
                    out = out[: int(len(out) * 0.88)]
                out += f'\n…[截断:预算 {budget} tok]'
        return out

    for pg in pages[:2]:
        seg = ''
        if level in ('summary', 'full'):
            st = section(pg['text'], '当前状态')
            kd = section(pg['text'], '关键判据·数字') or section(pg['text'], '关键判据')
            if level == 'full':
                seg = pg['text']
            else:
                seg = (st[:1200] + '\n' + kd[:900]).strip()
        if seg:
            parts.append(f'\n## 线页:{pg["title"]}\n{seg}')
    body = '\n'.join(parts)
    if tok(body) > budget:
        # 按预算裁剪:保留头部,尾部标注
        cut = body
        while tok(cut) > budget and len(cut) > 200:
            cut = cut[: int(len(cut) * 0.9)]
        body = cut + f'\n…[截断:原文 ~{tok(body)} tok,预算 {budget} tok]'
    return body


def main():
    ap = argparse.ArgumentParser(
    epilog='【契约】意图：开局给上下文（按预算分级）；只读\n退出码：0=成功；非0=缺正本/参数错\n失败后：缺文件→先 setup\n\n示例:\n  sp_dispatch.py --level pointer --cwd "$PWD"   # 开局默认(约 200 tok)\n  sp_dispatch.py --level summary --budget 900   # 要现状段\n  sp_dispatch.py --for codex --level summary    # 用 harness 默认预算(500)\n  sp_dispatch.py --line ssot-hub --level full --budget 4000\n\n要点:默认只给指针;全文只在被问到/显式 --level full 时拉。\n能力行来自 BUILD.json,chunks=0 时自动降级为「语义检索不可用」。',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--for', dest='harness', default='dsh')
    ap.add_argument('--cwd', default=os.getcwd())
    ap.add_argument('--level', choices=['pointer', 'summary', 'full'], default='pointer')
    ap.add_argument('--budget', type=int, default=None)
    ap.add_argument('--line', help='显式指定线页 slug')
    ap.add_argument('--preset', help='转生 preset(index-work/infra-ops/writing/generic)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    pages = line_pages()
    pre = None
    if a.preset:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sp_presets as P
        errs = P.validate(a.preset)
        if errs:
            sys.exit('❌ preset 引用失效:\n  - ' + '\n  - '.join(errs))
        pre = P.load()[a.preset]
        if pre.get('line'):
            a.line = pre['line']
    if a.line:
        picked = [p for p in pages if p['slug'] == a.line]
    else:
        picked = match(pages, a.cwd)
    budget = a.budget or (pre or {}).get('budget', {}).get(a.level) or HARNESS_BUDGET.get(a.harness, 700)
    out = render(a.level, picked, budget)
    if pre:
        ref, na, nol = P.brief(a.preset)
        head = f"- preset:{a.preset}({pre.get('desc','')})"
        if pre.get('asserts'):
            head += ' · 断言 ' + '/'.join(pre['asserts'][:8])
        body = out
        if tok(head + '\n' + body) > budget:      # preset 头也算进预算
            while tok(head + '\n' + body) > max(60, budget - 15) and len(body) > 120:
                body = body[: int(len(body) * 0.88)]
            body += f'\n…[截断:预算 {budget} tok]'
        out = head + '\n' + body
    log_use(a.level, budget, tok(out), [p['slug'] for p in picked], a.preset, a.harness)
    if a.json:
        print(json.dumps({'harness': a.harness, 'level': a.level, 'budget': budget,
                          'lines': [p['slug'] for p in picked], 'tokens': tok(out),
                          'capability': capability_line(), 'text': out}, ensure_ascii=False, indent=1))
    else:
        print(out)
        print(f"\n<!-- dispatch: harness={a.harness} level={a.level} budget={budget} actual≈{tok(out)} tok -->")


if __name__ == '__main__':
    main()

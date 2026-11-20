#!/usr/bin/env python3
"""sp_golden · golden 查询回归（退出/重建后不许把该召回的东西弄丢）

golden-queries.jsonl（profile/）：
  {"id":"g1","query":"...","expect_sids":["1a2b3c4d"],"expect_keywords":["..."]}

用法:
  python3 tools/sp_golden.py --init                # 建本机查询模板（不覆盖）
  python3 tools/sp_golden.py --suggest             # 从本机 lines/断言标题出候选
  python3 tools/sp_golden.py --capture --apply     # 记录当前 top-k 基线
  python3 tools/sp_golden.py --check               # 对照基线
  python3 tools/sp_golden.py --check --json --min-recall 0.8

判据：每条 query 的 top-k 与基线重合率 ≥ min-recall，且 expect_sids 至少命中一个。
无 :8399 / sp_semantic 不可用时 rc=2（测试可跳过）。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from ssotlib import cli  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
QUERIES = os.path.join(SSOT, 'profile', 'golden-queries.jsonl')
BASE = os.path.join(SSOT, 'profile', 'golden-baseline.json')
SEM = os.path.join(SSOT, 'tools', 'sp_semantic.py')
HIT_RX = re.compile(r'^\[([0-9.]+)\]\s+(\S+):(\d+)')
TEMPLATE = """# golden 查询模板：一行一个 JSON；由你的 agent 在本机生成/维护
# {"id":"g1","query":"某个只有你知道答案的问题","expect_sids":["1a2b3c4d"],"expect_keywords":["关键词"]}
"""


def init_template():
    if os.path.exists(QUERIES):
        print(f'已存在: {QUERIES}')
        return 0
    os.makedirs(os.path.dirname(QUERIES), exist_ok=True)
    with open(QUERIES, 'w', encoding='utf-8') as f:
        f.write(TEMPLATE)
    print(f'✅ 已建模板 {QUERIES}')
    print('   下一步：sp_golden.py --suggest 生成候选 → 人工/agent 补 expect_sids → --capture --apply')
    return 0


def suggest(limit=10, as_json=False):
    """从本机断言/主题/线页标题生成候选 query（只打印，不写盘）。"""
    cand, seen = [], set()
    generic = re.compile(r'(状态|在途|下一步|判据|指针|现在时|相关文件|设计约束|风险|边界|'
                         r'验收|口径|维护|变更|历史|时间线|背景|目标|方案|索引|迁移|踩过|'
                         r'已完成|待办|关键判据)', re.I)

    def add(q, src):
        q = re.sub(r'[*`_\[\]()#>]', '', q).strip()
        q = re.sub(r'^\d+[.、]\s*', '', q)
        if 8 <= len(q) <= 80 and not generic.search(q) and q not in seen:
            seen.add(q)
            cand.append({'id': f's{len(cand)+1}', 'query': q,
                         'expect_sids': [], 'source': src})

    # 1) 断言标题最具体
    ap = os.path.join(SSOT, 'knowledge', 'assertions.md')
    try:
        for line in open(ap, encoding='utf-8', errors='replace'):
            m = re.match(r'^##\s*A\d+\s*[·:：\-]\s*(.+?)\s*$', line)
            if m:
                add(m.group(1), 'assertion')
    except OSError:
        pass
    # 2) 主题页标题
    for p in sorted(glob.glob(os.path.join(SSOT, 'knowledge', 'topics', '*.md'))):
        try:
            for line in open(p, encoding='utf-8', errors='replace'):
                m = re.match(r'^#\s+(.+?)\s*$', line)
                if m:
                    add(m.group(1), 'topic')
                    break
        except OSError:
            continue
    # 3) 线页 H1（不再用通用 H2）
    for p in sorted(glob.glob(os.path.join(SSOT, 'lines', '*.md'))):
        try:
            for line in open(p, encoding='utf-8', errors='replace'):
                m = re.match(r'^#\s+(.+?)\s*$', line)
                if m:
                    add(m.group(1), 'line')
                    break
        except OSError:
            continue
    cand = cand[:limit]
    if as_json:
        print(json.dumps({'count': len(cand), 'queries': cand}, ensure_ascii=False, indent=1))
    else:
        print(f"候选 {len(cand)} 条（只打印；复制到 {QUERIES} 并补 expect_sids）")
        for x in cand:
            print(json.dumps(x, ensure_ascii=False))
    return 0 if cand else 2


def load_queries():
    out = []
    try:
        for line in open(QUERIES, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get('query'):
                out.append(d)
    except OSError:
        pass
    return out


def run_query(q, top):
    try:
        r = subprocess.run([sys.executable, SEM, q, '--top', str(top)],
                           capture_output=True, text=True, timeout=120)
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or f'rc={r.returncode}').strip()[:300]
    hits = []
    for line in r.stdout.splitlines():
        m = HIT_RX.match(line.strip())
        if m:
            hits.append({'score': float(m.group(1)), 'path': m.group(2), 'line': int(m.group(3))})
    return hits, ''


def capture(top, apply=False, as_json=False):
    qs = load_queries()
    if not qs:
        print(f'没有 golden 查询：{QUERIES}', file=sys.stderr)
        return 2
    out, errs = [], []
    for q in qs:
        hits, err = run_query(q['query'], top)
        if err:
            errs.append({'id': q.get('id'), 'error': err})
            continue
        out.append({'id': q.get('id') or q['query'][:12], 'query': q['query'],
                    'topk': [h['path'] for h in hits]})
    if errs:
        print(json.dumps({'ok': False, 'errors': errs}, ensure_ascii=False, indent=1), file=sys.stderr)
        return 2
    base = {'schema': 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'top': top,
            'model_fp': (json.load(open(os.path.join(SSOT, 'profile', 'embed-profile.json'),
                                        encoding='utf-8')).get('model_fp')
                         if os.path.exists(os.path.join(SSOT, 'profile', 'embed-profile.json')) else None),
            'queries': out}
    if apply:
        tmp = BASE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(base, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, BASE)
    if as_json:
        print(json.dumps({'applied': bool(apply), 'baseline': base}, ensure_ascii=False, indent=1))
    else:
        print(f"capture {len(out)} 条 / top={top}" + ('（已写 %s）' % BASE if apply else '（预览；加 --apply）'))
    return 0


def check(top, min_recall, as_json=False):
    qs = load_queries()
    try:
        base = json.load(open(BASE, encoding='utf-8'))
    except Exception:
        print(f'缺基线：{BASE}（先 --capture --apply）', file=sys.stderr)
        return 2
    bmap = {x['id']: x for x in base.get('queries') or []}
    rows, bad = [], 0
    for q in qs:
        qid = q.get('id') or q['query'][:12]
        b = bmap.get(qid)
        if not b:
            rows.append({'id': qid, 'ok': False, 'error': 'no baseline'})
            bad += 1
            continue
        hits, err = run_query(q['query'], top)
        if err:
            rows.append({'id': qid, 'ok': False, 'error': err})
            bad += 1
            continue
        cur = [h['path'] for h in hits]
        base_set = set(b.get('topk') or [])
        inter = len(base_set & set(cur))
        recall = inter / max(1, len(base_set))
        expect = [str(x) for x in (q.get('expect_sids') or [])]
        exp_hit = [e for e in expect if any(e in p for p in cur)]
        ok = recall >= min_recall and (not expect or bool(exp_hit))
        bad += 0 if ok else 1
        rows.append({'id': qid, 'ok': ok, 'recall': round(recall, 3),
                     'expect_hit': exp_hit, 'baseline': len(base_set), 'current': len(cur)})
    out = {'ok': bad == 0, 'min_recall': min_recall, 'rows': rows}
    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"golden: {'PASS' if bad == 0 else 'FAIL'}（{len(rows)} 条，失败 {bad}，min_recall={min_recall}）")
        for r in rows:
            print(f"  {'ok  ' if r.get('ok') else 'FAIL'} {r['id']}: recall={r.get('recall', '-')} "
                  f"expect={r.get('expect_hit', r.get('error', '-'))}")
    return 0 if bad == 0 else 1


def main():
    ap = cli.base_parser(epilog='示例:\n  sp_golden.py --capture --apply\n  sp_golden.py --check', root=False)
    ap.add_argument('--init', action='store_true', help='在 profile/ 建查询模板（不存在才写）')
    ap.add_argument('--suggest', action='store_true', help='从本机 lines/断言标题生成候选 query（只打印）')
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--min-recall', type=float, default=0.8)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.init:
        return init_template()
    if a.suggest:
        return suggest(a.limit, a.json)
    if a.capture:
        return capture(a.top, a.apply, a.json)
    if a.check:
        return check(a.top, a.min_recall, a.json)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())

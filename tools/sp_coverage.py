#!/usr/bin/env python3
"""sp_coverage · 覆盖审计:每个 harness 的会话,原始 → S1 → 索引,缺口一眼可见

判据(2026-10-31)：一条命令回答"是否全量抽取完毕"。
只读:不写 evidence、不改索引。空壳会话(0KB transcript)单列,不算丢失。

用法:
  python3 tools/sp_coverage.py            # 表 + 一行结论
  python3 tools/sp_coverage.py --json     # 机读
"""
import argparse, glob, json, os, sqlite3, sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
DB = os.path.join(SSOT, 'S2-index/semantic/index.db')
HOME = os.path.expanduser('~')

# 已接入的源: (名称, S0 原始目录, S1 目录)
SOURCES = [
    ('qoder', 'evidence/qoder/S0-archive/qoder-projects', 'evidence/qoder/S1-sessions'),
    ('opencode', '~/.local/share/opencode/opencode.db', 'evidence/opencode/S1-sessions'),
    ('cc', 'evidence/cc/S0-archive/claude-projects', 'evidence/cc/S1-sessions'),
    ('dsh', 'evidence/dsh/S0-archive/dsh-sessions', 'evidence/dsh/S1-sessions'),
    ('pi', 'evidence/pi/S0-archive/pi-sessions', 'evidence/pi/S1-sessions'),
]
# 未接入的源: 原始件路径(逐条给它数出来,缺口才具体)
PENDING = [
    ('codex', os.path.join(HOME, '.codex/sessions'), 'jsonl'),
]
ROLE_FILE = os.path.join(SSOT, 'profile', 'sources.json')


def roles():
    try:
        d = json.load(open(ROLE_FILE, encoding='utf-8'))
        return {k: v for k, v in d.items() if not k.startswith('_')}
    except Exception:
        return {}


EMPTY_BYTES = 1                 # transcript 0 字节 = 空壳(占位会话)
GLOBAL_SIDS = set()              # qoder 跨项目全局去重用


def opencode_root_count(con):
    """OpenCode 根会话数：session_v2 优先，legacy 只补 id 不在 v2 的会话。

    2026-11-06：旧实现只数 legacy session（冻结在 10-25），v2 新会话永远进不了
    分母，导致「未接入 0」的假绿。
    """
    has_v2 = bool(con.execute(
        "select 1 from sqlite_master where type='table' and name='session_v2'").fetchone())
    has_legacy = bool(con.execute(
        "select 1 from sqlite_master where type='table' and name='session'").fetchone())
    n = 0
    if has_v2:
        n += con.execute("select count(*) from session_v2 where parent_id is null").fetchone()[0]
    if has_legacy:
        if has_v2:
            n += con.execute(
                "select count(*) from session where parent_id is null "
                "and id not in (select id from session_v2)").fetchone()[0]
        else:
            n += con.execute("select count(*) from session where parent_id is null").fetchone()[0]
    return n


def count_raw(src, raw_dir):
    """按各源真实布局数会话;opencode 直接读 sqlite(只读)"""
    if raw_dir.endswith('.db'):
        try:
            con = sqlite3.connect(f'file:{os.path.expanduser(raw_dir)}?mode=ro', uri=True, timeout=10)
            n = opencode_root_count(con) if src == 'opencode' else con.execute(
                "select count(*) from session where parent_id is null").fetchone()[0]
            con.close()
            return n
        except Exception:
            return 0
    p = os.path.join(SSOT, raw_dir)
    if not os.path.isdir(p):
        return 0
    n = 0
    for proj in glob.glob(p + '/*'):
        if not os.path.isdir(proj):
            continue
        if src == 'qoder':          # 同一 sid 可能既有目录又有 .jsonl,且跨项目重复 → 全局去重
            for ent in glob.glob(proj + '/*'):
                name = os.path.basename(ent)
                GLOBAL_SIDS.add(name[:-6] if name.endswith('.jsonl') else name)
        elif src == 'dsh':
            for e in glob.glob(proj + '/*'):
                if not os.path.isdir(e):
                    continue
                f2 = os.path.join(e, 'session.v4.jsonl.zstd')
                if os.path.exists(f2) and os.path.getsize(f2) >= 2048:
                    n += 1
        else:                        # cc / pi
            n += len(glob.glob(proj + '/*.jsonl'))
    return n if src != 'qoder' else len(GLOBAL_SIDS)


def s1_stats(s1_dir, tiny_bytes=2048):
    p = os.path.join(SSOT, s1_dir)
    if not os.path.isdir(p):
        return 0, 0, set(), 0
    dirs, empty, names, tiny = 0, 0, set(), 0
    for d in glob.glob(p + '/*'):
        if not os.path.isdir(d):
            continue
        dirs += 1
        names.add(os.path.basename(d))
        f = os.path.join(d, 'transcript.jsonl')
        if not os.path.exists(f) or os.path.getsize(f) < EMPTY_BYTES:
            empty += 1
        elif os.path.getsize(f) < tiny_bytes:
            tiny += 1
    return dirs, empty, names, tiny


def indexed_map():
    """→ {src: (会话集合, 块数)}"""
    out = {}
    if not os.path.exists(DB):
        return out
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=15)
    rows = con.execute("SELECT path, COUNT(*) FROM chunks WHERE path LIKE 'evidence/%' GROUP BY path").fetchall()
    con.close()
    for p, n in rows:
        parts = p.split('/')
        if len(parts) < 4 or parts[0] != 'evidence':
            continue
        src = parts[1]
        sess, blocks = out.get(src, (set(), 0))
        blocks += n
        if len(parts) > 3 and parts[2] == 'S1-sessions':
            sess.add(parts[3])
        out[src] = (sess, blocks)
    return out


def pending_count(kind, path):
    if kind == 'jsonl':
        if not os.path.isdir(path):
            return 0
        return len([f for f in glob.glob(path + '/**/*.jsonl', recursive=True)])
    if kind == 'sqlite':
        if not os.path.exists(path):
            return 0
        try:
            con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
            n = opencode_root_count(con)
            con.close()
            return n
        except Exception:
            return 0
    return 0


def collect():
    idx = indexed_map()
    rows = []
    for src, raw_dir, s1_dir in SOURCES:
        raw = count_raw(src, raw_dir)
        n1, empty, names, tiny = s1_stats(s1_dir)
        sub = len(glob.glob(os.path.join(SSOT, s1_dir.replace('S1-sessions', 'S1-subagents'), '*')))
        sess, blocks = idx.get(src, (set(), 0))
        covered = len(names & sess)
        need = max(0, n1 - empty - tiny)
        rows.append({'src': src, 'raw': raw, 's1': n1, 'empty': empty,
                     'indexed': len(sess), 'covered': covered, 'blocks': blocks,
                     'gap_s1': max(0, raw - n1), 'gap_idx': max(0, n1 - empty - covered),
                     'tiny': tiny, 'need': need, 'sub': sub,
                     'status': 'ok' if n1 and covered >= need else ('partial' if n1 else 'none')})
    pending = []
    for src, path, kind in PENDING:
        pending.append({'src': src, 'raw': pending_count(kind, path), 's1': 0, 'indexed': 0,
                        'blocks': 0, 'status': 'missing'})
    return rows, pending


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_coverage.py\n  sp_coverage.py --json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    rows, pending = collect()
    if a.json:
        print(json.dumps({'sources': rows, 'pending': pending}, ensure_ascii=False, indent=1))
        return 0
    rl = roles()
    print(f"{'源':10s}{'角色':6s}{'原始':>6s}{'S1':>6s}{'子':>4s}{'空壳':>6s}{'已索引':>8s}{'块':>9s}  状态")
    for r in rows:
        role = (rl.get(r['src']) or {}).get('role', 'human')
        print(f"{r['src']:10s}{role:6s}{r['raw']:6d}{r['s1']:6d}{r.get('sub', 0):4d}{r['empty']:6d}{r['covered']:8d}{r['blocks']:9d}  {r['status']}")
    for p in pending:
        role = (rl.get(p['src']) or {}).get('role', 'human')
        state = 'tool(不抽取)' if role == 'tool' else 'missing(未接入)'
        print(f"{p['src']:10s}{role:6s}{p['raw']:6d}{'—':>6s}{'—':>6s}{'—':>8s}{'—':>9s}  {state}")
    human_raw = sum(r['raw'] for r in rows) + sum(p['raw'] for p in pending
                                                  if (rl.get(p['src']) or {}).get('role', 'human') != 'tool')
    tool_raw = sum(r['raw'] for r in pending if (rl.get(p['src']) or {}).get('role') == 'tool')
    tot_idx = sum(r['covered'] for r in rows)
    miss = sum(p['raw'] for p in pending if (rl.get(p['src']) or {}).get('role', 'human') != 'tool')
    tail = []
    if miss:
        tail.append('未接入 ' + ', '.join(f"{p['src']} {p['raw']}" for p in pending
                                          if (rl.get(p['src']) or {}).get('role', 'human') != 'tool' and p['raw']))
    if tool_raw:
        tail.append(f"tool 源跳过 {tool_raw}(" + ','.join(p['src'] for p in pending
                     if (rl.get(p['src']) or {}).get('role') == 'tool') + ')')
    print(f"\n结论:已索引 {tot_idx}/{human_raw} 人类源会话" + ('；' + '；'.join(tail) if tail else '；无未接入源'))
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

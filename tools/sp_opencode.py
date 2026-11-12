#!/usr/bin/env python3
"""sp_opencode · opencode 会话(sqlite) → S1 五件套

设计:§5.4。只读打开(ro + busy_timeout)。v2 为主（session_v2/session_message），
legacy 只补未迁移会话（session/message/part）；不再假设 session_part 有数据。
输出:evidence/opencode/S1-sessions/<date>-<sid8>-<slug>/

用法:
  python3 tools/sp_opencode.py --list                 # 列出会话(不写)
  python3 tools/sp_opencode.py --dry-run --limit 2    # 看会产出什么
  python3 tools/sp_opencode.py --all --force          # 全量重转(v2 迁移后)
  python3 tools/sp_opencode.py --db /tmp/x.db --root /tmp/r   # 测试用
"""
import argparse, datetime, json, os, re, sqlite3, sys, time

SSOT = os.path.expanduser('~/ssot')
DB = os.path.expanduser('~/.local/share/opencode/opencode.db')
STATE = os.path.join(SSOT, 'logs', '.opencode-state.json')


def conn(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=20)


def sid_of(session_id):
    s = re.sub(r'^ses_', '', session_id)
    return re.sub(r'[^0-9a-zA-Z]', '', s)[:8]


def slugify(title):
    t = re.sub(r'[^\w\u4e00-\u9fff]+', '-', (title or 'untitled')).strip('-')
    return t[:40] or 'untitled'


def table_exists(con, name):
    return bool(con.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone())


def sessions_of(con, limit=None):
    """→ [(id,title,created,dir,updated,parent,store)]；v2 优先，legacy 只补未迁移会话。"""
    rows = []
    if table_exists(con, 'session_v2'):
        rows += [tuple(r) + ('session_v2',) for r in con.execute(
            "SELECT id,title,time_created,directory,time_updated,parent_id FROM session_v2")]
    if table_exists(con, 'session'):
        rows += [tuple(r) + ('session',) for r in con.execute(
            "SELECT id,title,time_created,directory,time_updated,parent_id FROM session "
            "WHERE id NOT IN (SELECT id FROM session_v2)" if table_exists(con, 'session_v2') else
            "SELECT id,title,time_created,directory,time_updated,parent_id FROM session")]
    rows.sort(key=lambda s: s[4] or 0, reverse=True)
    return rows[:limit] if limit else rows


def rows_of_legacy(con, session_id):
    """legacy message/part → [(ts, role, text)]。"""
    out = []
    for mid, ts, data in con.execute(
            "SELECT id, time_created, data FROM message WHERE session_id=? ORDER BY time_created", (session_id,)):
        try:
            md = json.loads(data or '{}')
        except Exception:
            md = {}
        role = md.get('role', '?')
        texts = []
        for (pdata,) in con.execute("SELECT data FROM part WHERE message_id=? ORDER BY time_created", (mid,)):
            try:
                pd = json.loads(pdata or '{}')
            except Exception:
                continue
            if pd.get('type') == 'text' and pd.get('text'):
                texts.append(pd['text'])
            elif pd.get('type') in ('tool', 'tool_call', 'tool_result'):
                texts.append('[tool]')
        if texts:
            out.append((ts, role, '\n'.join(texts)))
    return out


def rows_of_v2(con, session_id):
    """session_message.data → [(ts, role, text)]。正文/工具都在 data，session_part 可空。"""
    out = []
    for _mid, mtype, ts, data in con.execute(
            "SELECT id,type,time_created,data FROM session_message WHERE session_id=? ORDER BY seq,time_created",
            (session_id,)):
        try:
            md = json.loads(data or '{}')
        except Exception:
            continue
        role, text = None, ''
        if mtype == 'user':
            role = 'user'
            text = md.get('text') or ''
            if not text and isinstance(md.get('content'), list):
                text = '\n'.join(c.get('text', '') for c in md['content']
                                 if isinstance(c, dict) and c.get('type') == 'text')
        elif mtype == 'assistant':
            role = 'assistant'
            parts = []
            for c in (md.get('content') or []):
                if not isinstance(c, dict):
                    continue
                if c.get('type') == 'text' and c.get('text'):
                    parts.append(c['text'])
                elif c.get('type') == 'tool':
                    name = c.get('name') or 'tool'
                    state = c.get('state') or {}
                    inp = state.get('input') or {}
                    brief = inp.get('command') or inp.get('description') or inp.get('path') or ''
                    parts.append(f'[tool] {name}' + (f': {str(brief)[:240]}' if brief else ''))
            text = '\n'.join(parts)
        elif mtype == 'system':
            role, text = 'system', md.get('text') or ''
        elif mtype == 'compaction':
            role, text = 'system', md.get('summary') or ''
        # synthetic/idle/agent-switched/model-switched 不入正文（注入上下文/状态事件）
        if role and text.strip():
            out.append((ts, role, text))
    return out


def rows_of(con, session_id, store='session_v2'):
    """v2 优先；v2 无正文时回退 legacy（迁移未完成的旧会话）。"""
    if store == 'session_v2' and table_exists(con, 'session_message'):
        rows = rows_of_v2(con, session_id)
        if rows:
            return rows
    if table_exists(con, 'message'):
        return rows_of_legacy(con, session_id)
    return []


def write_s1(root, con, s, force=False):
    sid = sid_of(s[0])
    is_sub = s[5] is not None            # parent_id 非空 = 子 agent 会话(不参与人类抽取)
    store = s[6] if len(s) > 6 else 'session'
    base = 'S1-subagents' if is_sub else 'S1-sessions'
    ts = datetime.datetime.fromtimestamp(s[2] / 1000).strftime('%Y-%m-%d') if s[2] else '1970-01-01'
    d = os.path.join(root, 'evidence', 'opencode', base, f'{ts}-{sid}-{slugify(s[1])}')
    tr = os.path.join(d, 'transcript.jsonl')
    if os.path.exists(tr) and not force:
        return d, 0
    rows = rows_of(con, s[0], store)
    if not rows:                       # 无正文的会话不落盘(否则覆盖率永远差一条)
        return d, 0
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump({'sid': sid, 'src': 'opencode', 'session_id': s[0], 'title': s[1],
                   'dir': s[3], 'created': s[2], 'updated': s[4],
                   'origin': 'subagent' if is_sub else 'human',
                   'store': store, 'schema_version': 1, 'schema': 2}, f, ensure_ascii=False, indent=1)
    with open(tr, 'w', encoding='utf-8') as f:
        for i, (mts, role, text) in enumerate(rows, 1):
            f.write(json.dumps({'t': datetime.datetime.fromtimestamp(mts / 1000).astimezone().isoformat() if mts else '',
                                'role': role, 'uuid': f'{sid}-{i}', 'parent': None,
                                'kind': 'text', 'content': text}, ensure_ascii=False) + '\n')
    with open(os.path.join(d, 'transcript.md'), 'w', encoding='utf-8') as f:
        f.write(f'# {s[1]}\n\n> opencode · {sid}\n\n')
        for mts, role, text in rows:
            f.write(f'**{role}**: {text[:800]}\n\n')
    with open(os.path.join(d, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump({'sid': sid, 'title': s[1], 'rows': len(rows), 'store': store}, f, ensure_ascii=False)
    open(os.path.join(d, 'raw.jsonl'), 'w').close()
    return d, len(rows)


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_opencode.py --list\n  sp_opencode.py --dry-run --limit 2\n  sp_opencode.py --limit 5',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=DB)
    ap.add_argument('--root', default=SSOT)
    ap.add_argument('--limit', type=int, default=5)
    ap.add_argument('--all', action='store_true', help='转换全部会话（等价 --limit 0）')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print(f'❌ 找不到 {a.db}'); return 1
    con = conn(a.db)
    limit = None if a.all or a.limit == 0 else a.limit
    sessions = sessions_of(con, limit)
    if a.list or a.dry_run:
        print(f"{'sid':10s}{'store':12s}{'更新':12s}{'目录':28s}标题")
        for s in sessions:
            up = datetime.datetime.fromtimestamp(s[4] / 1000).strftime('%m-%d %H:%M') if s[4] else '?'
            print(f"{sid_of(s[0]):10s}{s[6]:12s}{up:12s}{(s[3] or '')[-26:]:28s}{(s[1] or '')[:40]}")
        if a.dry_run:
            print(f'\n[dry] 将转换 {len(sessions)} 个会话（不写盘）')
        return 0
    done = rows_total = 0
    for s in sessions:
        d, n = write_s1(a.root, con, s, a.force)
        done += 1; rows_total += n
        print(f"  {sid_of(s[0])} +{n} 行 → {os.path.relpath(d, a.root)}")
    con.close()
    print(f'✅ 转换 {done} 个会话 / {rows_total} 行')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)

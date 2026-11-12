#!/usr/bin/env python3
"""scan_sessions · 枚举本机 Qoder 会话（只读，不修改任何文件）→ TSV

用法:
  python3 scan_sessions.py [--qoder-dir ~/.qoder] [--app-db PATH] [--limit N]

输出（按最近活动倒序，制表符分隔，无表头）:
  日期    工作区    会话id    消息数    标题    类别

类别:
  flat / transcript / nested    盘上布局（平铺 / 旧档 transcript/ / 目录布局）
  上述 + "+app"                盘上有文件且 app 主库能对上（标题/日期取 app 权威值）
  上述 + "-only"               盘上有、app 主库无
  app-only                     app 主库有、盘上无主转录

覆盖三种盘上布局 + app 主库（chat_sessions），按 sid8 前缀双向补全。
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys

APP_DB_CANDIDATES = [
    os.path.expanduser('~/Library/Application Support/com.qoder.app.stable/main.sqlite'),
    os.path.expanduser('~/Library/Application Support/com.qoder.app/main.sqlite'),
]
SID_RE = re.compile(r'^[0-9a-zA-Z][0-9a-zA-Z-]{7,}$')


def read_session(jsonl_path):
    """返回 (消息行数, 首条用户消息摘要)。只读到标题出现为止。"""
    n, title = 0, ''
    skip_prefixes = ('<system-reminder>', '[Request interrupted', 'Caveat:',
                     'This session is being continued', '<user-pasted-text')
    try:
        with open(jsonl_path, encoding='utf-8', errors='replace') as f:
            for line in f:
                n += 1
                if title:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('type') != 'user' or d.get('isSidechain'):
                    continue
                msg = d.get('message', {})
                c = msg.get('content') if isinstance(msg, dict) else None
                if isinstance(c, str):
                    text = c
                elif isinstance(c, list) and c:
                    first = c[0]
                    text = first.get('text', '') if isinstance(first, dict) else str(first)
                else:
                    continue
                text = ' '.join(str(text).split())
                if text and not text.startswith(skip_prefixes):
                    title = text
    except Exception as e:
        return n, f'(读取失败: {e})'
    return n, title[:100]


def app_sessions(db_path):
    """读 app 主库（只读）→ {session_id: {title,cwd,ts,msgs}}；失败返回 {}。"""
    if not db_path or not os.path.exists(db_path):
        return {}
    try:
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        rows = con.execute(
            'select session_id, title, cwd, updated_at from chat_sessions').fetchall()
        counts = dict(con.execute(
            'select session_id, count(*) from chat_session_messages group by session_id'))
        out = {}
        for sid, title, cwd, upd in rows:
            try:
                ts = float(upd)
                if ts > 1e12:          # 毫秒 → 秒
                    ts /= 1000.0
            except Exception:
                ts = 0.0
            out[sid] = {'title': ' '.join((title or '').split())[:100],
                        'cwd': ' '.join((cwd or '').split()),
                        'ts': ts, 'msgs': counts.get(sid, 0)}
        return out
    except Exception as e:
        print(f'⚠️ app 主库读取失败（{e}）；本次只报盘上会话', file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qoder-dir', default=os.path.expanduser('~/.qoder'))
    ap.add_argument('--app-db', default=os.environ.get('QODER_APP_DB', ''),
                    help='默认自动探测 stable/main.sqlite')
    ap.add_argument('--limit', type=int, default=0, help='只显示最近 N 个（0=全部）')
    a = ap.parse_args()

    proj = os.path.join(a.qoder_dir, 'projects')
    if not os.path.isdir(proj):
        print(f'❌ 找不到 {proj} —— 若本机会话不在 Qoder，请改用其自带会话列表工具', file=sys.stderr)
        sys.exit(1)

    # ── 盘上三布局：递归 walk，排除 subagents/ ──
    disk = {}
    for dp, dns, fns in os.walk(proj):
        dns[:] = [d for d in dns if d != 'subagents' and not d.startswith('.')]
        for fn in fns:
            if not fn.endswith('.jsonl'):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, proj)
            parts = rel.split(os.sep)
            if len(parts) < 2:
                continue
            ws = parts[0]
            sid = fn[:-len('.jsonl')]
            if not SID_RE.match(sid):
                # 目录布局：主转录若在 <ws>/<sid>/ 下，用目录名当 sid
                if len(parts) >= 3 and SID_RE.match(parts[1]):
                    sid = parts[1]
                else:
                    continue
            if len(parts) == 2:
                cls = 'flat'
            elif len(parts) == 3 and parts[1] == 'transcript':
                cls = 'transcript'
            else:
                cls = 'nested'
            mtime = os.path.getmtime(p)
            st = os.path.join(proj, ws, sid, 'state.json')
            if os.path.exists(st):
                try:
                    mtime = max(mtime, os.path.getmtime(st))
                except OSError:
                    pass
            n, title = read_session(p)
            old = disk.get(sid)
            if old and old['cls'] == 'flat':
                continue
            disk[sid] = {'ws': ws, 'sid': sid, 'msgs': n, 'title': title,
                         'ts': mtime, 'cls': cls}

    # ── app 主库：双向补全 ──
    db = a.app_db
    if not db:
        db = next((p for p in APP_DB_CANDIDATES if os.path.exists(p)), '')
    app = app_sessions(db)
    app8 = {}
    for sid in app:
        app8.setdefault(sid[:8], []).append(sid)

    rows, matched = [], set()
    for sid, r in disk.items():
        hit = sid if sid in app else None
        if not hit:
            cand = app8.get(sid[:8], [])
            if len(cand) == 1:
                hit = cand[0]
        if hit:
            ar = app[hit]
            matched.add(hit)
            r.update(msgs=r['msgs'] or ar['msgs'], title=ar['title'] or r['title'],
                     ts=max(r['ts'], ar['ts']), cls=r['cls'] + '+app')
        else:
            r['cls'] += '-only'
        rows.append(r)

    for sid, ar in app.items():
        if sid in matched:
            continue
        rows.append({'ws': ar['cwd'] or '(app)', 'sid': sid, 'msgs': ar['msgs'],
                     'title': ar['title'], 'ts': ar['ts'], 'cls': 'app-only'})

    rows.sort(key=lambda r: r['ts'], reverse=True)
    if a.limit:
        rows = rows[:a.limit]
    for r in rows:
        dt = datetime.datetime.fromtimestamp(r['ts']).strftime('%Y-%m-%d') if r['ts'] else '-'
        print(f"{dt}\t{r['ws']}\t{r['sid']}\t{r['msgs']}\t{r['title']}\t{r['cls']}")
    n_app = sum(1 for r in rows if r['cls'] == 'app-only')
    print(f'# 共 {len(rows)} 个会话（盘上 {len(disk)} + app-only {n_app}）', file=sys.stderr)


if __name__ == '__main__':
    main()

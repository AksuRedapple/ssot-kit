#!/usr/bin/env python3
"""sp_convert · S0 → S1 四件套转换器 (v0.3)
用法:
  python3 sp_convert.py --sid 4c767364 [--title "名称"] [--force]
  python3 sp_convert.py --all / --incremental [--src qoder|cc|pi]
纪律: 只读 S0；输出幂等；纯标准库。
v0.2（2026-10-14）：①派生层脱敏通道（密钥形态串写前替换；raw 锚点不动）
                    ②工具结果截 500 字入派生层（原先只有占位符，命令输出不可搜）
                    ③接续链：压缩摘要里检出上一片段 sid → meta.cont_from + md 标注
v0.3（2026-10-14）：标题提纯——跳过寒暄/命令包装/终端粘贴，取首个实质消息；改标题时清理旧目录
v0.4（2026-10-15）：①压缩边界补 uuid/logical_parent（起点指针）+ prev/next 链（真实数据，不合成）
                    ②md 截断加回取锚点「+N 字 · 全文见 transcript.jsonl」（量维持 3000/2500）
                    ③meta 增 first_uuid/last_uuid（跨压缩稳定锚）
v0.5（2026-10-25）：接入 Pi（--src pi）——v3 树形 jsonl 适配：message/toolCall/toolResult/
                    compaction/branch_summary/custom_message；system 段（提示词+工具声明）不入派生层；
                    sid 取会话头 id（文件名是 <ts>_<uuid>）；session_info.name 作标题可被 --title 覆盖。
"""
import argparse, datetime, hashlib, json, os, re, shutil, sys

SECRET_RX = [
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[REDACTED-SECRET]'),
    (re.compile(r'sk-[0-9a-f]{5,31}(?![0-9a-f])'), '[REDACTED-SECRET]'),  # 被截断/显示的短前缀残形
    (re.compile(r'ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'), '[REDACTED-SECRET]'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED-SECRET]'),
    (re.compile(r'hf_[A-Za-z0-9]{30,}'), '[REDACTED-SECRET]'),
    (re.compile(r'(?i)bearer\s+[A-Za-z0-9._\-]{30,}'), '[REDACTED-SECRET]'),
]


def scrub(text):
    for rx, rep in SECRET_RX:
        text = rx.sub(rep, text)
    return text

VAULT = os.path.expanduser('~/ssot')
SRCS = {
    'qoder': ('evidence/qoder/S0-archive/qoder-projects', 'evidence/qoder/S1-sessions'),
    'cc':    ('evidence/cc/S0-archive/claude-projects',   'evidence/cc/S1-sessions'),
    'pi':    ('evidence/pi/S0-archive/pi-sessions',       'evidence/pi/S1-sessions'),
    'dsh':   ('evidence/dsh/S0-archive/dsh-sessions',     'evidence/dsh/S1-sessions'),
}
CUR_SRC = 'qoder'
S0 = os.path.join(VAULT, SRCS[CUR_SRC][0])
S1 = os.path.join(VAULT, SRCS[CUR_SRC][1])
CONVERTER = 'sp_convert v0.5'


def contract_schema():
    """实例契约号（profile/contract.json）；无契约文件→None（旧实例不盖章）。

    S1 meta 的 schema 必须由生成器自己盖（契约 v2 · 见 A530）。
    """
    try:
        d = json.load(open(os.path.join(VAULT, 'profile', 'contract.json'), encoding='utf-8'))
        return int(d.get('contract', 0)) or None
    except Exception:
        return None

DROP_TYPES = {'attachment', 'runtime-config', 'workspace-directories',
              'active-leaf', 'worktree-state', 'file-history-snapshot', 'last-prompt'}

def local(ts):
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return dt + datetime.timedelta(hours=8)
    except Exception:
        return None

def lstr(ts, fmt='%m-%d %H:%M'):
    d = local(ts)
    return d.strftime(fmt) if d else str(ts)[:16]

def norm_content(content):
    """→ (kind, payload)  kind ∈ text|tool_use|tool_result|empty"""
    if isinstance(content, str):
        return ('text', content) if content.strip() else ('empty', '')
    if isinstance(content, list):
        texts, tools, results = [], [], []
        for x in content:
            if not isinstance(x, dict):
                continue
            t = x.get('type')
            if t == 'text' and str(x.get('text', '')).strip():
                texts.append(x['text'])
            elif t == 'tool_use':
                brief = json.dumps(x.get('input') or {}, ensure_ascii=False)
                tools.append({'name': x.get('name', '?'), 'brief': brief[:300]})
            elif t == 'tool_result':
                c = x.get('content')
                if isinstance(c, list):
                    c = ' '.join(str(y.get('text', '')) for y in c if isinstance(y, dict))
                results.append(str(c or '')[:500])
        if texts:
            return ('text', '\n'.join(texts))
        if tools:
            return ('tool_use', tools)
        if results:
            return ('tool_result', results)
    return ('empty', '')

def slugify(s, n=40):
    s = re.sub(r'[^\w\u4e00-\u9fff\-]+', '-', s).strip('-')
    return (s[:n].strip('-') or 'session')


def pi_load(path):
    """Pi v3 jsonl → (events, meta)。events 与 Qoder/CC 同形，复用主循环。

    映射：user/assistant 文本、toolCall→tool_use、toolResult→user+tool_result、
         compaction→compact_boundary+压缩摘要、branch_summary/custom_message→user 文本。
    丢弃：system 段（提示词/工具声明/开机注入，体积大且不可搜）、thinking、image、usage/custom 等状态行。
    """
    events, meta = [], {}
    with open(path) as f:
        for ln in f:
            try:
                o = json.loads(ln)
            except Exception:
                continue
            t = o.get('type')
            ts = o.get('timestamp', '')
            eid, parent = o.get('id'), o.get('parentId')
            if t == 'session':
                meta = {'sid': o.get('id'), 'cwd': o.get('cwd'),
                        'version': o.get('version'), 'header_ts': ts,
                        'parent_session': o.get('parentSession')}
                continue
            if t == 'session_info':
                if o.get('name'):
                    meta['name'] = o['name']
                continue
            if t == 'message':
                m = o.get('message') or {}
                role = m.get('role')
                content = m.get('content')
                blocks = content if isinstance(content, list) else [{'type': 'text', 'text': content}]
                if role == 'user':
                    texts = [b.get('text', '') for b in blocks
                             if isinstance(b, dict) and b.get('type') == 'text' and str(b.get('text', '')).strip()]
                    if texts:
                        events.append({'type': 'user', 'timestamp': ts, 'uuid': eid,
                                       'message': {'parentUuid': parent,
                                                   'content': [{'type': 'text', 'text': '\n'.join(texts)}]}})
                elif role == 'assistant':
                    texts = [b.get('text', '') for b in blocks
                             if isinstance(b, dict) and b.get('type') == 'text' and str(b.get('text', '')).strip()]
                    tools = [{'type': 'tool_use', 'name': b.get('name', '?'), 'input': b.get('arguments') or {}}
                             for b in blocks if isinstance(b, dict) and b.get('type') == 'toolCall']
                    if texts:
                        events.append({'type': 'assistant', 'timestamp': ts, 'uuid': eid,
                                       'message': {'parentUuid': parent,
                                                   'content': [{'type': 'text', 'text': '\n'.join(texts)}]}})
                    if tools:
                        events.append({'type': 'assistant', 'timestamp': ts, 'uuid': None,
                                       'message': {'parentUuid': parent, 'content': tools}})
                elif role == 'toolResult':
                    txt = '\n'.join(b.get('text', '') for b in blocks
                                    if isinstance(b, dict) and b.get('type') == 'text')
                    events.append({'type': 'user', 'timestamp': ts, 'uuid': eid,
                                   'message': {'parentUuid': parent,
                                               'content': [{'type': 'tool_result', 'content': txt}]}})
                continue
            if t == 'compaction':
                summary = o.get('summary', '') or ''
                events.append({'type': 'system', 'subtype': 'compact_boundary', 'timestamp': ts,
                               'uuid': eid, 'logicalParentUuid': parent, 'content': summary,
                               'compactMetadata': {'trigger': 'auto', 'preTokens': o.get('tokensBefore')}})
                if summary.strip():
                    # 复用主循环的 compact_summary 通道（→ summary.md + summaries）
                    events.append({'type': 'user', 'timestamp': ts, 'uuid': None,
                                   'message': {'parentUuid': parent,
                                               'content': [{'type': 'text',
                                                            'text': 'This session is being continued from a previous conversation.\n\n' + summary}]}})
                continue
            if t == 'branch_summary':
                txt = (o.get('summary') or '').strip()
                if txt:
                    events.append({'type': 'user', 'timestamp': ts, 'uuid': eid,
                                   'message': {'parentUuid': parent,
                                               'content': [{'type': 'text', 'text': '[分支摘要] ' + txt}]}})
                continue
            if t == 'custom_message':
                c = o.get('content')
                txt = c if isinstance(c, str) else '\n'.join(
                    b.get('text', '') for b in (c or []) if isinstance(b, dict))
                if str(txt or '').strip():
                    events.append({'type': 'user', 'timestamp': ts, 'uuid': eid,
                                   'message': {'parentUuid': parent,
                                               'content': [{'type': 'text',
                                                            'text': f"[扩展注入:{o.get('customType', '?')}] " + txt}]}})
                continue
    return events, meta


def session_sid(path):
    """Pi 的文件名是 <ts>_<uuid>.jsonl，sid 只能从会话头取；其它源用文件名。"""
    if CUR_SRC == 'pi':
        try:
            with open(path) as f:
                return json.loads(f.readline()).get('id') or os.path.basename(path)
        except Exception:
            return os.path.basename(path)
    return os.path.basename(path)[:-6]

TITLE_GREET_RX = re.compile(
    r'^(你好|您好|hi|hello|在吗|在么|早上好|晚安|谢谢|多谢|好的|嗯+|ok|1)[!！。.~？?\s]*$', re.I)

def title_ok(txt):
    """标题候选判据：够长、非寒暄、非命令包装/斜杠命令、非终端提示符粘贴"""
    t = txt.strip()
    if len(t) < 8:
        return False
    if TITLE_GREET_RX.match(t):
        return False
    if t[0] in '<[/':
        return False
    if re.match(r'^[\w.\-]+@[\w.\-]+\s*[%~$#]', t):
        return False
    return True

def convert(path, title_override=None, force=False):
    pi_meta = {}
    if CUR_SRC == 'pi':
        events, pi_meta = pi_load(path)
        sid = pi_meta.get('sid') or os.path.basename(path)
        if title_override is None and pi_meta.get('name'):
            title_override = pi_meta['name']
    else:
        sid = os.path.basename(path)[:-6]
        events = []
        with open(path) as f:
            for ln in f:
                try:
                    events.append(json.loads(ln))
                except Exception:
                    pass

    counts = {'user': 0, 'assistant': 0, 'tool_use': 0, 'compactions': 0}
    compactions, goals, rows = [], [], []
    summaries = []          # 压缩摘要全文
    first_ts = last_ts = None
    first_user_text = None
    title_candidates = []   # 供标题提纯：前 10 条用户实质消息
    title = title_override
    md = {}                 # day(本地) -> [行]

    def md_add(ts, s):
        d = local(ts)
        md.setdefault(d.strftime('%Y-%m-%d') if d else 'unknown', []).append(s)

    for o in events:
        t = o.get('type')
        ts = o.get('timestamp', '')
        if not isinstance(ts, str):
            ts = ''
        if ts:
            if first_ts is None: first_ts = ts
            last_ts = ts
        if t in DROP_TYPES:
            continue
        if t == 'system' and o.get('subtype') == 'compact_boundary':
            cm = o.get('compactMetadata') or {}
            compactions.append({'at': ts, 'trigger': cm.get('trigger'),
                                'preTokens': cm.get('preTokens'),
                                'messagesSummarized': cm.get('messagesSummarized'),
                                'postTokens': cm.get('postTokens')})
            counts['compactions'] += 1
            rows.append({'t': ts, 'role': 'system', 'uuid': o.get('uuid'),
                         'logical_parent': o.get('logicalParentUuid'),
                         'kind': 'compact_boundary', 'content': o.get('content', ''), 'meta': cm})
            lp = (o.get('logicalParentUuid') or '')[:8]
            md_add(ts, f"\n---\n\n## ⌦ 压缩边界（{lstr(ts)} · {cm.get('trigger','?')} · 总结 {cm.get('messagesSummarized','?')} 条 → {cm.get('postTokens','?')} tokens{f' · 起点 {lp}' if lp else ''}）\n")
            continue
        if t not in ('user', 'assistant'):
            continue
        msg = o.get('message') or {}
        kind, payload = norm_content(msg.get('content', ''))

        if kind == 'tool_use':
            counts['tool_use'] += len(payload)
            rows.append({'t': ts, 'role': 'assistant', 'uuid': o.get('uuid'),
                         'parent': msg.get('parentUuid'), 'kind': 'tool_use', 'tools': payload})
            brief = '; '.join(f"{x['name']}({x['brief'][:80]})" for x in payload[:4])
            md_add(ts, f"`[工具] {brief}`\n")
            continue
        if kind != 'text':
            if t == 'user' and kind == 'tool_result' and payload:
                res = '\n'.join(payload)[:500]
                rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'),
                             'parent': msg.get('parentUuid'), 'kind': 'tool_result',
                             'content': res})
                short = res.replace('\n', ' ')[:150]
                md_add(ts, f"`[结果] {short}{'…' if len(res) > 150 else ''}`\n")
            elif t == 'user' and kind == 'empty':
                rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'),
                             'parent': msg.get('parentUuid'), 'kind': 'meta',
                             'content': '[系统事件]'})
            continue

        txt = payload.strip()
        if not txt:
            continue
        # 特殊消息族
        if txt.startswith('This session is being continued'):
            rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'),
                         'parent': msg.get('parentUuid'), 'kind': 'compact_summary', 'content': txt})
            summaries.append({'at': ts, 'text': txt})
            md_add(ts, f"\n### ⟳ {lstr(ts)} 压缩摘要注入（全文见 summary.md）\n")
            continue
        if txt.startswith('Continue working toward the active thread goal'):
            rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'), 'kind': 'goal_tick',
                         'content': '[goal 推轮]'})
            md_add(ts, f"*{lstr(ts)} goal 守望推轮（自动）*\n")
            continue
        if 'A goal has been set' in txt and '<untrusted_objective>' in txt:
            m = re.search(r'<untrusted_objective>(.*?)</untrusted_objective>', txt, re.S)
            obj = (m.group(1).strip() if m else txt)[:800]
            goals.append({'at': ts, 'objective': obj})
            rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'), 'kind': 'goal_set',
                         'content': obj})
            md_add(ts, f"\n### 🎯 {lstr(ts)} goal 设定\n\n{obj[:400]}\n")
            continue
        if 'Request interrupted' in txt:
            rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'), 'kind': 'meta',
                         'content': txt})
            md_add(ts, f"*{lstr(ts)} 用户中断*\n")
            continue

        # 常规消息
        if t == 'user':
            counts['user'] += 1
            if first_user_text is None:
                first_user_text = txt
            if len(title_candidates) < 10:
                title_candidates.append(txt)
            rows.append({'t': ts, 'role': 'user', 'uuid': o.get('uuid'),
                         'parent': msg.get('parentUuid'), 'kind': 'text', 'content': txt})
            md_add(ts, f"\n### 🧑 用户 · {lstr(ts)}\n\n{txt[:3000]}"
                   f"{f'…〔+{len(txt) - 3000} 字 · 全文见 transcript.jsonl〕' if len(txt) > 3000 else ''}\n")
        else:
            counts['assistant'] += 1
            rows.append({'t': ts, 'role': 'assistant', 'uuid': o.get('uuid'),
                         'parent': msg.get('parentUuid'), 'kind': 'text', 'content': txt})
            md_add(ts, f"\n🤖 **助手** · {lstr(ts)}\n\n{txt[:2500]}"
                   f"{f'…〔+{len(txt) - 2500} 字 · 全文见 transcript.jsonl〕' if len(txt) > 2500 else ''}\n")

    # v0.4：压缩边界前后链（prev/next = 最近的带 uuid 消息，真实指针非合成）
    for i, r in enumerate(rows):
        if r.get('kind') == 'compact_boundary':
            for pr in reversed(rows[:i]):
                if pr.get('uuid'):
                    r['prev_uuid'] = pr['uuid']
                    break
            for nx in rows[i + 1:]:
                if nx.get('uuid'):
                    r['next_uuid'] = nx['uuid']
                    break

    # v0.2：接续链检测（压缩摘要里含上一片段 jsonl 路径 → 记 sid8）
    cont_from = None
    for s in summaries:
        m = re.search(r'([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl',
                      s['text'])
        if m:
            cont_from = m.group(1)
            break

    # 命名与目录
    if not title:
        pick = next((c for c in title_candidates if title_ok(c)), None)
        title = (pick or first_user_text or sid)[:40].replace('\n', ' ')
    title = scrub(title)
    start_d = local(first_ts) if first_ts else datetime.datetime.now()
    dirname = f"{start_d.strftime('%Y-%m-%d')}-{sid[:8]}-{slugify(title)}"
    outdir = os.path.join(S1, dirname)
    # 标题提纯可能改变目录名：先清同一 sid 的旧片段目录（S1 为派生物，raw/S0 是锚点）
    for dd in sorted(os.listdir(S1)):
        od = os.path.join(S1, dd)
        if od == outdir or f'-{sid[:8]}-' not in dd or not os.path.isdir(od):
            continue
        try:
            if json.load(open(os.path.join(od, 'meta.json'))).get('sid') == sid:
                shutil.rmtree(od)
                print(f"  🧹 旧目录已清: {dd}")
        except Exception:
            pass
    os.makedirs(outdir, exist_ok=True)

    # raw.jsonl 实体副本
    raw_dst = os.path.join(outdir, 'raw.jsonl')
    shutil.copy2(path, raw_dst)

    # sha256（源）
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    sha = h.hexdigest()

    # transcript.jsonl（v0.2：逐行脱敏后写）
    with open(os.path.join(outdir, 'transcript.jsonl'), 'w') as f:
        for r in rows:
            f.write(scrub(json.dumps(r, ensure_ascii=False)) + '\n')

    # transcript.md（v0.2：整体脱敏；接续链标注）
    # cwd（Pi 取会话头；Qoder/CC 取事件）
    cwd = events[0].get('directories', [None])[0] if events and events[0].get('type') == 'workspace-directories' else None
    if not cwd and pi_meta.get('cwd'):
        cwd = pi_meta['cwd']
    if not cwd:
        for o in events:
            if o.get('cwd'):
                cwd = o['cwd']
                break

    md_out = [f"# {title}\n\n",
              f"> sid `{sid}` · cwd `{cwd or '未知'}`\n",
              f"> {lstr(first_ts, '%Y-%m-%d %H:%M')} → {lstr(last_ts, '%Y-%m-%d %H:%M')} · "
              f"用户 {counts['user']} / 助手 {counts['assistant']} / 工具调用 {counts['tool_use']} / 压缩 {counts['compactions']} 次\n"]
    if cont_from:
        md_out.append(f"> 接续自 `{cont_from}…`（上一片段）\n")
    md_out.append(f"> 来源 sha256 `{sha[:16]}…`（全量见 meta.json）· 生成 {datetime.datetime.now():%Y-%m-%d %H:%M} · {CONVERTER}\n\n")
    for day in sorted(md):
        md_out.append(f"\n# ── {day} ──\n")
        md_out.append(''.join(md[day]))
    with open(os.path.join(outdir, 'transcript.md'), 'w') as f:
        f.write(scrub(''.join(md_out)))

    # summary.md（v0.2：脱敏后写）
    sm_out = [f"# {title} · 压缩摘要集\n\n"]
    if not summaries:
        sm_out.append('（无压缩事件）\n')
    for s in summaries:
        sm_out.append(f"\n## {lstr(s['at'], '%Y-%m-%d %H:%M')}\n\n{s['text']}\n\n---\n")
    with open(os.path.join(outdir, 'summary.md'), 'w') as f:
        f.write(scrub(''.join(sm_out)))

    # meta.json
    smoke = (cwd == '/') or str(first_user_text or '').startswith('reply with exactly')
    uuids = [r.get('uuid') for r in rows if r.get('uuid')]
    meta = {
        'sid': sid, 'title': title, 'cwd': cwd,
        'smoke': smoke,
        'start': first_ts, 'end': last_ts,
        'counts': counts,
        'compactions': compactions,
        'goals': goals,
        'cont_from': cont_from,
        'first_uuid': uuids[0] if uuids else None,
        'last_uuid': uuids[-1] if uuids else None,
        'src': CUR_SRC,
        'source': {'path': os.path.relpath(path, VAULT), 'sha256': sha,
                   'size': os.path.getsize(path)},
        'converted_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'converter': CONVERTER,
    }
    schema = contract_schema()
    if schema:
        meta['schema'] = schema
    with open(os.path.join(outdir, 'meta.json'), 'w') as f:
        f.write(scrub(json.dumps(meta, ensure_ascii=False, indent=2)))
    return outdir, counts, len(rows)

def main():
    ap = argparse.ArgumentParser(
    epilog='【契约】意图：原始会话→S1 五件套；只读原件\n退出码：0=完成；非0=源缺失/解析失败（跳过）\n失败后：看失败会话；原件不动，可重跑\n\n示例:\n  sp_convert.py --src dsh --incremental     # 增量转换(按 meta.converted_at 与源 mtime)\n  sp_convert.py --src qoder --all            # 全量\n  sp_convert.py --src cc --sid 4c767364      # 单个会话\n判据:四数齐(会话数/行数/角色分布/时间线)+ 抽样文本无乱码。',
    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sid', help='会话 id 前缀')
    ap.add_argument('--title', help='覆盖标题')
    ap.add_argument('--all', action='store_true', help='全量转换（主会话文件）')
    ap.add_argument('--incremental', action='store_true', help='增量：只转 S1 缺失或源有更新的会话')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--src', choices=['qoder', 'cc', 'pi', 'dsh'], default='qoder', help='证据源（默认 qoder）')
    a = ap.parse_args()

    if a.src == 'dsh':
        import sp_dsh
        argv = ['sp_dsh.py']
        if a.incremental: argv.append('--incremental')
        if a.all: argv.append('--all')
        if a.sid: argv += ['--sid', a.sid]
        sys.argv = argv
        sp_dsh.main()
        return

    global S0, S1, CUR_SRC
    CUR_SRC = a.src
    S0 = os.path.join(VAULT, SRCS[a.src][0])
    S1 = os.path.join(VAULT, SRCS[a.src][1])
    os.makedirs(S1, exist_ok=True)

    targets = []
    for slug in sorted(os.listdir(S0)):
        d = os.path.join(S0, slug)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.jsonl') and os.path.isfile(os.path.join(d, fn)):
                targets.append(os.path.join(d, fn))
    if a.sid:
        targets = [p for p in targets if session_sid(p).startswith(a.sid)]
        if not targets:
            sys.exit(f'未找到会话前缀 {a.sid}')
    elif a.incremental:
        keep = []
        for p in targets:
            sid8 = session_sid(p)[:8]
            hit = None
            for dd in os.listdir(S1):
                mp0 = os.path.join(S1, dd, 'meta.json')
                try:
                    if json.load(open(mp0)).get('sid', '').startswith(sid8):
                        hit = os.path.join(S1, dd)
                        break
                except Exception:
                    continue
            if hit is None:
                keep.append(p)  # S1 缺失
                continue
            mp = os.path.join(hit, 'meta.json')
            try:
                ca = json.load(open(mp)).get('converted_at', '')
                ca_epoch = datetime.datetime.fromisoformat(ca).timestamp()
                if os.path.getmtime(p) > ca_epoch:
                    keep.append(p)  # 源有更新
            except Exception:
                keep.append(p)
        targets = keep
    elif not a.all:
        sys.exit('请给 --sid / --all / --incremental')

    for p in targets:
        try:
            outdir, counts, n = convert(p, a.title, a.force)
            print(f"✅ {os.path.basename(outdir)}  ({n} 行· 用户{counts['user']}/助手{counts['assistant']}/工具{counts['tool_use']}/压缩{counts['compactions']})")
        except Exception as e:
            print(f"❌ {os.path.basename(p)}: {e}")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""sp_triage · 会话收尾的「候选 → 人审 A/R → inbox」段(2026-10-31)

三段式里最后一段的机械化:extract 出表 → 人挑 A/R → accept 写 inbox(只追加)。
复用 sp_extract 的 score()/sentences()(import,不复制);staging 格式沿用 cand.v1 之外的
轻量行格式(本工具只产 markdown 表 + 消费序号),不另造一套候选库。

用法:
  python3 sp_triage.py extract --sid 4c767364 [--since 2026-10-13] [--top 40]
  python3 sp_triage.py accept  --sid 4c767364 --ids 1,3,5 [--line dpt-third-screen] [--dry-run] [--reject]
  python3 sp_triage.py status [--since 2026-10-01]

回退:删 inbox/.triage-state.jsonl + 不再调用钩子。
"""
import argparse, datetime, glob, hashlib, importlib.util, json, os, re, sys

SSOT = os.path.expanduser('~/ssot')
ROOT = os.environ.get('ZB_TRIAGE_ROOT') or SSOT     # 测试隔离用:不改生产 inbox
OUT = os.path.join(ROOT, 'compile')
INBOX = os.path.join(ROOT, 'inbox')
STATE = os.path.join(INBOX, '.triage-state.jsonl')
ALERTS = os.path.join(ROOT, 'alerts', 'steward.log')
LOG = os.path.join(ROOT, 'alerts', 'triage.log')

TYPE_RX = [
    ('decision', r'(决定|定案|拍板|结论是|改成|采用|以后不|owner\s*[:=])'),
    ('insight', r'(教训|坑|反直觉|本质|经验是|原来)'),
    ('fact', r'(实测|验证|复现|根因|数字|ms|MB|GB|%)'),
]


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%F %T} {msg}\n')


def load_extract():
    p = os.path.join(SSOT, 'tools', 'sp_extract.py')
    spec = importlib.util.spec_from_file_location('sp_extract', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def s1_dirs(sid):
    out = []
    for base in glob.glob(os.path.join(ROOT, 'evidence', '*', 'S1-sessions')):
        for d in sorted(glob.glob(os.path.join(base, '*'))):
            if sid in os.path.basename(d) and os.path.isfile(os.path.join(d, 'transcript.jsonl')):
                out.append(d)
    return out


def clean_sentence(s):
    """剔除 JSON/转义残片与半截句,只留像人话的句子"""
    B = chr(92)
    t = s.replace(B + 'n', ' ').replace(B + '"', '"').replace(B + 't', ' ')
    if B in t or '{"' in t:
        return ''
    if re.match(r'^[\s→·\-—*#>|`]', t):
        return ''
    cjk = len(re.findall('[\u4e00-\u9fff]', t))
    if cjk < 6:
        return ''
    if re.search(r'(\w+_\w+|::|\(\)|\{\}|\[\])', t) and cjk < 12:
        return ''
    return t


def classify(text):
    for t, rx in TYPE_RX:
        if re.search(rx, text):
            return t
    return 'fact'


LEDGER = os.path.join(ROOT, 'inbox', 'candidates', 'candidates.jsonl')


def extract_from_ledger(sid, since=None, top=40):
    """从唯一账本取候选(2026-10-31 通道归一):不再重扫 transcript"""
    items = []
    if not os.path.exists(LEDGER):
        return items
    for ln in open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            c = json.loads(ln)
        except Exception:
            continue
        ev = (c.get('evidence') or [{}])[0]
        sess = str(ev.get('session', ''))
        if sid not in sess:
            continue
        ts = str(c.get('first_seen') or ev.get('ts') or '')[:10]
        if since and ts and ts < since:
            continue
        if c.get('state') in ('rejected', 'duplicate', 'duplicate-known'):
            continue
        items.append((c.get('claim', ''), int(ev.get('line') or 0), c.get('type', 'fact'), c.get('state', '')))
    return items[:top]


def ledger_counts(sid):
    """→ (total, eligible)；total=账本里该 sid 的全部行，eligible=未被拒/去重的行。"""
    total = eligible = 0
    if not os.path.exists(LEDGER):
        return 0, 0
    for ln in open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            c = json.loads(ln)
        except Exception:
            continue
        ev = (c.get('evidence') or [{}])[0]
        if sid not in str(ev.get('session', '')):
            continue
        total += 1
        if c.get('state') not in ('rejected', 'duplicate', 'duplicate-known'):
            eligible += 1
    return total, eligible


def extract(sid, since=None, top=40, legacy=False):
    if not legacy:
        items = extract_from_ledger(sid, since, top)
        total, eligible = ledger_counts(sid)
        if total == 0:
            dst = write_table(sid, [], source_note='账本 candidates.jsonl(唯一)',
                              reason='uncollected')
            print('⚠ 该会话未进账本（S1/导出器未采集），不是“0 候选”')
            print('  先查 S1：ls -d ~/ssot/evidence/*/S1-sessions/*<sid8>*')
            return dst, [], 'uncollected'
        if not items:
            dst = write_table(sid, [], source_note='账本 candidates.jsonl(唯一)',
                              reason='rejected')
            print(f'候选 0 条（账本有 {total} 条，均被拒/去重；不是低分）')
            return dst, [], 'rejected'
        dst, items = write_table(sid, items, source_note='账本 candidates.jsonl(唯一)')
        return dst, items, 'ok'
    EX = load_extract()
    cands = {}
    for d in s1_dirs(sid):
        tj = os.path.join(d, 'transcript.jsonl')
        for i, raw in enumerate(open(tj, encoding='utf-8', errors='replace'), 1):
            try:
                r = json.loads(raw)
            except Exception:
                continue
            ts = str(r.get('t') or '')
            if since and ts[:10] < since:
                continue
            for s in EX.sentences(r.get('content', '') or ''):
                s = clean_sentence(s)
                if not s:
                    continue
                sc = EX.score(s)
                if sc >= 4 and s not in cands:
                    cands[s] = (sc, i, r.get('role', ''))
    items = sorted(cands.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[:top]
    dst, items = write_table(sid, [(s, v[1], classify(s), 'legacy') for s, v in items],
                             source_note='transcript(legacy)')
    return dst, items, 'ok'


def write_table(sid, items, source_note='', reason=None):
    dst = os.path.join(OUT, f'triage-{sid}-{datetime.date.today().isoformat()}.md')
    os.makedirs(OUT, exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(f'# 收尾候选 · {sid}\n\n')
        f.write(f'> 来源: {source_note} · **只列表,判断留人**\n\n')
        f.write('| # | 候选行 | 类型 | 建议 source | 出处行号 | 裁决 |\n|---|---|---|---|---|---|\n')
        for n, (txt, line, typ, _st) in enumerate(items, 1):
            f.write(f'| {n} | {txt[:160].replace(chr(124), chr(65372))} | {typ} | `{sid}:L{line}` | {line} | [ ]A [ ]R |\n')
        if not items:
            if reason == 'uncollected':
                note = '该会话未进账本（S1/导出器未采集），不是“0 候选”'
            elif reason == 'rejected':
                note = '账本有记录，但候选均被拒/去重；不是低分'
            else:
                note = '0 条候选：该会话没有达到打分阈值的句子'
            f.write(f'| — | ({note}) | — | — | — | — |\n')
    if items:
        print(f'候选 {len(items)} 条 → {os.path.relpath(dst, ROOT)}')
    else:
        label = {'uncollected': '未采集', 'rejected': '全被拒/去重'}.get(reason, '真低分')
        print(f'候选 0 条（{label}）→ {os.path.relpath(dst, ROOT)}')
    if items:
        print(f'→ 跑 sp_triage accept --sid {sid} --ids <序号,逗号分隔>')
    return dst, items


def load_state():
    rows = []
    if os.path.exists(STATE):
        for ln in open(STATE, encoding='utf-8', errors='replace'):
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    return rows


def key_of(sid, line, text):
    return hashlib.sha1(f'{sid}|{line}|{text}'.encode('utf-8')).hexdigest()[:16]


def parse_table(sid):
    """读当天(或最近)的 triage 表 → {序号: (text, line, type)}"""
    files = sorted(glob.glob(os.path.join(OUT, f'triage-{sid}-*.md')))
    if not files:
        return {}, None
    f = files[-1]
    rows = {}
    for ln in open(f, encoding='utf-8', errors='replace'):
        m = re.match(r'\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(\w+)\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|', ln)
        if m:
            rows[int(m.group(1))] = (m.group(2), int(m.group(5)), m.group(3))
    return rows, f


def accept(sid, ids, line=None, dry=False, reject=False):
    rows, src = parse_table(sid)
    if not rows:
        print(f'候选 0 条(没有 triage 表:{sid})')
        return 0
    state = load_state()
    state_keys = {r['key']: r for r in state}
    new_state, out_lines = [], []
    today = datetime.date.today().isoformat()
    for n in ids:
        if n not in rows:
            print(f'⚠ 序号 {n} 不存在(表里只有 1..{max(rows)})')
            continue
        text, lineno, typ = rows[n]
        k = key_of(sid, lineno, text)
        if k in state_keys:
            continue                      # 幂等:同候选只处理一次
        if reject:
            new_state.append({'key': k, 'ts': today, 'sid': sid, 'line': lineno,
                              'verdict': 'R', 'text': text[:120]})
            continue
        seg = [f'- {today} [{typ}] {text[:200]}', f'source: {sid}:L{lineno}']
        if line:
            seg.append(f'line: {line}')
        seg.append('conf: 待核')
        out_lines.append(' | '.join(seg))
        new_state.append({'key': k, 'ts': today, 'sid': sid, 'line': lineno,
                          'verdict': 'A', 'text': text[:120]})
    if dry:
        print(f'[dry-run] 将写 {len(out_lines)} 行 / 拒绝 {sum(1 for s in new_state if s["verdict"]=="R")} 条(不落盘)')
        for l in out_lines:
            print('  ' + l)
        return 0
    if out_lines:
        dst = os.path.join(INBOX, f'{today}.md')
        old = open(dst, encoding='utf-8').read() if os.path.exists(dst) else ''
        tmp = dst + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(old)
                if old and not old.endswith('\n'):
                    f.write('\n')
                f.write('\n'.join(out_lines) + '\n')
            if os.environ.get('ZB_TRIAGE_FAIL_AFTER_TMP') == '1':   # 测试注入:模拟中途失败
                raise RuntimeError('injected failure before rename')
            os.replace(tmp, dst)              # 原子替换:要么整份新,要么原样
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    if new_state:
        with open(STATE, 'a', encoding='utf-8') as f:
            for s in new_state:
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
    print(f'已 A {len(out_lines)} 行 / 已 R {sum(1 for s in new_state if s["verdict"]=="R")} 条'
          f'（表:{os.path.basename(src or "")}）')
    return 0


def status(since=None):
    state = load_state()
    A = sum(1 for r in state if r.get('verdict') == 'A' and (not since or r.get('ts', '') >= since))
    R = sum(1 for r in state if r.get('verdict') == 'R' and (not since or r.get('ts', '') >= since))
    n, pend, old = 0, 0, 0
    done = {r['key'] for r in state}
    today = datetime.date.today()
    for f in glob.glob(os.path.join(OUT, 'triage-*.md')):
        d = os.path.basename(f)[len('triage-'):-3]
        sid = d.rsplit('-', 3)[0]
        try:
            fdate = datetime.date.fromisoformat('-'.join(d.rsplit('-', 3)[-3:]))
        except Exception:
            fdate = today
        for ln in open(f, encoding='utf-8', errors='replace'):
            m = re.match(r'\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*\w+\s*\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|', ln)
            if not m:
                continue
            n += 1
            k = key_of(sid, int(m.group(4)), m.group(2))
            if k not in done:
                pend += 1
                if (today - fdate).days > 3:
                    old += 1
    print(f'候选 {n} / 已 A {A} / 已 R {R} / 超 3 天未处理 {old}')
    return 0


def note_alert(ncand, A, R, pend):
    try:
        os.makedirs(os.path.dirname(ALERTS), exist_ok=True)
        with open(ALERTS, 'a', encoding='utf-8') as f:
            f.write(f'{datetime.datetime.now():%m-%d %H:%M} [triage] candidates={ncand} accepted={A} rejected={R} pending={pend}\n')
    except Exception as e:  # noqa: BLE001
        log(f'alert 写入失败: {e}')


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sp_contract import guard as _contract_guard
    if not _contract_guard('sp_triage', write=True):
        return 2
    ap = argparse.ArgumentParser(epilog='【契约】意图：候选→审阅表→A/R→收件箱；不写正本\n退出码：0=成功；2=契约不符\n失败后：契约不符→sp_migrate\n\n示例:\n  sp_triage.py extract --sid 4c767364 --top 40\n  sp_triage.py accept --sid 4c767364 --ids 1,3 --line dpt-third-screen\n  sp_triage.py status --since 2026-10-01',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract'); e.add_argument('--sid', required=True); e.add_argument('--since'); e.add_argument('--top', type=int, default=40)
    e.add_argument('--legacy-from-s1', action='store_true', help='旧路径:重扫 transcript(仅当该会话还没进账本)')
    a = sub.add_parser('accept'); a.add_argument('--sid', required=True); a.add_argument('--ids', required=True)
    a.add_argument('--line'); a.add_argument('--dry-run', action='store_true'); a.add_argument('--reject', action='store_true')
    s = sub.add_parser('status'); s.add_argument('--since')
    args = ap.parse_args()

    try:
        if args.cmd == 'extract':
            dst, items, state = extract(args.sid, args.since, args.top, legacy=args.legacy_from_s1)
            st = load_state()
            A = sum(1 for r in st if r.get('verdict') == 'A'); R = sum(1 for r in st if r.get('verdict') == 'R')
            note_alert(len(items), A, R, max(0, len(items)))
            return 2 if state == 'uncollected' else 0
        if args.cmd == 'accept':
            ids = [int(x) for x in re.split(r'[,\s]+', args.ids) if x.strip().isdigit()]
            rc = accept(args.sid, ids, args.line, args.dry_run, args.reject)
            if not args.dry_run:
                st = load_state()
                A = sum(1 for r in st if r.get('verdict') == 'A'); R = sum(1 for r in st if r.get('verdict') == 'R')
                note_alert(0, A, R, 0)
            return rc
        return status(args.since)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 —— extract 失败不阻断(硬约束 3)
        log(f'{args.cmd} EXC {type(e).__name__}: {e}')
        if args.cmd == 'extract':
            print(f'候选 0 条(抽取异常:{e};已记 alerts/triage.log)')
            return 0
        print(f'❌ accept 失败:{e}')
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)

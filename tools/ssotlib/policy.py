"""索引生命周期策略（session_class / retired）单一实现

消费方：sp_index / sp_coverage / sp_classify / sp_exit / ssot_check。
只读 profile/index-policy.json 与 profile/retired.jsonl；不做写入（写由 sp_classify/sp_exit 负责）。
"""
import json
import os
import re

from . import store

CLASSES = ('human', 'automation', 'monitor', 'decision', 'unknown')
DEFAULT_INCLUDE = ['human', 'decision', 'unknown']
DEFAULT_SKIP = ['automation', 'monitor']
POLICY_REL = os.path.join('profile', 'index-policy.json')
RETIRED_REL = os.path.join('profile', 'retired.jsonl')


def _root(root=None):
    return os.path.expanduser(root or os.environ.get('SSOT_ROOT', '~/ssot'))


def load_policy(root=None):
    root = _root(root)
    p = os.path.join(root, POLICY_REL)
    base = {'schema': 1, 'enabled': False, 'include': list(DEFAULT_INCLUDE),
            'skip': list(DEFAULT_SKIP), 'rules': [], 'heuristics': False}
    d = store.read_json_strict(p, None, label='索引策略 index-policy.json')
    if not isinstance(d, dict):
        return base
    base.update({k: v for k, v in d.items() if k in
                 ('schema', 'enabled', 'include', 'skip', 'rules', 'heuristics')})
    if 'enabled' not in d:
        base['enabled'] = True
    base['include'] = [str(x) for x in (base.get('include') or [])]
    base['skip'] = [str(x) for x in (base.get('skip') or [])]
    base['rules'] = base.get('rules') if isinstance(base.get('rules'), list) else []
    return base


def load_retired(root=None):
    """→ (set(sid), {sid: event})；后写覆盖先写。"""
    root = _root(root)
    p = os.path.join(root, RETIRED_REL)
    state = {}
    try:
        for line in open(p, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            sid = str(e.get('sid') or '')
            if not sid:
                continue
            state[sid] = e
    except OSError:
        pass
    retired = {s for s, e in state.items() if e.get('op') != 'unretire'}
    return retired, state


def class_of(meta):
    c = str((meta or {}).get('session_class') or 'human').lower()
    return c if c in CLASSES else 'unknown'


def harness_of(rel):
    parts = str(rel).split('/')
    return parts[1] if len(parts) > 1 and parts[0] == 'evidence' else '-'


def sid_of(meta, rel=''):
    sid = str((meta or {}).get('sid') or '')
    if sid:
        return sid
    base = os.path.basename(os.path.dirname(str(rel)))
    m = re.match(r'^\d{4}-\d{2}-\d{2}-([0-9a-f-]{8,})', base)
    return m.group(1) if m else base[:8]


def _match(rule, ctx):
    m = rule.get('match') if isinstance(rule, dict) else None
    if not isinstance(m, dict):
        return False
    for key, val in m.items():
        if key == 'harness':
            if val != ctx.get('harness'):
                return False
        elif key == 'sid_prefix':
            if not str(ctx.get('sid', '')).startswith(str(val)):
                return False
        elif key.endswith('_regex'):
            field = key[:-6]
            if not re.search(str(val), str(ctx.get(field) or ''), re.I):
                return False
        else:
            if str(val).lower() not in str(ctx.get(key) or '').lower():
                return False
    return True


def suggest_class(meta, rel='', policy=None):
    """→ (class, reason, source)；规则优先，其次已有值，最后 human。"""
    policy = policy or {}
    meta = meta or {}
    ctx = {'harness': harness_of(rel), 'sid': sid_of(meta, rel),
           'cwd': meta.get('cwd') or '', 'title': meta.get('title') or '',
           'project': ((meta.get('source') or {}).get('path') or ''),
           'source': ((meta.get('source') or {}).get('path') or '')}
    existing0 = str(meta.get('session_class') or '').lower()
    if meta.get('class_source') == 'manual' and existing0 in CLASSES:
        return existing0, str(meta.get('class_reason') or 'manual'), 'manual'
    for r in policy.get('rules') or []:
        if isinstance(r, dict) and _match(r, ctx):
            cls = str(r.get('class') or '').lower()
            if cls in CLASSES:
                return cls, str(r.get('reason') or 'rule match'), 'rule'
    existing = str(meta.get('session_class') or '').lower()
    if existing in CLASSES:
        return existing, str(meta.get('class_reason') or 'existing'), 'existing'
    if policy.get('heuristics'):
        title = ctx['title']
        cwd = ctx['cwd']
        if re.search(r'(值守|监控|巡检|定时|heartbeat|watchdog|monitor)', title + ' ' + cwd, re.I):
            return 'monitor', 'heuristic: 值守/监控关键词', 'heuristic'
        if re.search(r'(自动|auto|nightly|cron|schedule)', title + ' ' + cwd, re.I):
            return 'automation', 'heuristic: 自动/定时关键词', 'heuristic'
    return 'human', 'default', 'default'


def included(cls, policy=None, all_classes=False, only=None):
    policy = policy or {}
    if all_classes:
        return True
    if only:
        return cls in set(only)
    if not policy.get('enabled'):
        return True
    if cls in set(policy.get('skip') or []):
        return False
    return True


def summary(policy=None, retired_count=0):
    policy = policy or {}
    if not policy.get('enabled'):
        return 'disabled（全部入索引）'
    return ('include=%s skip=%s retired=%d' %
            (','.join(policy.get('include') or []),
             ','.join(policy.get('skip') or []), retired_count))

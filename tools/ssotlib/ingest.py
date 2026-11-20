"""采集/入库共用件：密钥脱敏、内容归一化、时区转换、丢弃类型。

这些口径原来长在 `sp_convert`（S1 转换器）里，却被归档、巡检、子 agent 派生
三个工具反向 import。抽出来后 `tools → ssotlib` 的依赖方向才成立。
"""
import datetime
import json
import re

# 密钥形态 → 统一替换（顺序有意义：先长后短，避免短前缀把长 key 截断）
SECRET_RX = [
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '[REDACTED-SECRET]'),
    (re.compile(r'sk-[0-9a-f]{5,31}(?![0-9a-f])'), '[REDACTED-SECRET]'),  # 被截断/显示的短前缀残形
    (re.compile(r'ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'), '[REDACTED-SECRET]'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED-SECRET]'),
    (re.compile(r'hf_[A-Za-z0-9]{30,}'), '[REDACTED-SECRET]'),
    (re.compile(r'(?i)bearer\s+[A-Za-z0-9._\-]{30,}'), '[REDACTED-SECRET]'),
]


def scrub(text):
    """把密钥形态替换成 [REDACTED-SECRET]；非字符串原样返回。"""
    for rx, rep in SECRET_RX:
        text = rx.sub(rep, text)
    return text


DROP_TYPES = {'attachment', 'runtime-config', 'workspace-directories',
              'active-leaf', 'worktree-state', 'file-history-snapshot', 'last-prompt'}


def local(ts):
    """ISO 时间 → UTC+8；无法解析返回 None。"""
    try:
        dt = datetime.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        return dt + datetime.timedelta(hours=8)
    except Exception:
        return None


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

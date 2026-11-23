"""采集/入库共用件：密钥脱敏、内容归一化、时区转换、丢弃类型。

这些口径原来长在 `sp_convert`（S1 转换器）里，却被归档、巡检、子 agent 派生
三个工具反向 import。抽出来后 `tools → ssotlib` 的依赖方向才成立。
"""
import datetime
import json

from . import secrets

# 向后兼容：既有工具把 SECRET_RX 当 [(rx, rep)]（隐私闸/findall）。
# 分级规则与置信度在 ssotlib/secrets.py（2026-11-23 · P2）。
SECRET_RX = secrets.SECRET_RX


def scrub(text):
    """把 high + 有上下文的 medium 密钥替换成 [REDACTED-SECRET]；非字符串原样返回。

    不再替换无上下文的 `sk-<hex>`（low）——旧规则会把 `task-<hex>` / `ask-at-poorest`
    的词尾改成密钥（2026-11-22 实测 S0 565 处误伤）。
    """
    if not isinstance(text, str):
        return text
    return secrets.scrub(text, level='medium')


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

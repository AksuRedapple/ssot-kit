"""会话读取的唯一入口（三种形状 + 系统注入过滤）

存在理由（2026-11-10 评审团 P0）：三个工具各自内联 CC 解析，跨 harness 全是空集；
且把 task-notification / system-reminder 当成"用户消息"，条数虚高 28%。

支持形状:
  CC 原件     {"type":"user","message":{"content":[...]},"isSidechain":bool,"timestamp":...}
  CC sidechain 同上，isSidechain=true → 默认跳过
  Codex rollout {"type":"response_item","payload":{"type":"message","role":"user","content":[...]}}
  S1 五件套   {"t":..., "role":"user","kind":"text","content":"..."}  （dsh/opencode/pi/qoder/cc 归一）

过滤:
  - tool_result-only 消息
  - 系统注入：<system-reminder> / <task-notification> / <local-command* / [SYSTEM NOTIFICATION / Caveat: / "This session is being continued"
  - 空文本

契约: 只读；流式（不整载）；**零输入由调用方判为错误，不许当通过**。
"""
import json

SYSTEM_MARKERS = (
    "# AGENTS.md instructions",
    "<environment_context>",
    "<system-reminder>",
    "<task-notification>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<command-name>",
    "[SYSTEM NOTIFICATION",
    "Caveat:",
    "This session is being continued",
    # 2026-11-22：本机 harness 自己的注入面（此前被当成人类消息，C5 虚高数倍）
    "<paseo-system",
    "[paseo-warmer]",
    "[ssot-context]",
    "[SSOT 提醒]",
    "[SSOT 强制]",
    "Time sampled while preparing",
    "Current runtime context",
    "Base directory for this skill",
)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"):
                parts.append(b.get("text", ""))
        return "\n".join(parts)
    return ""


def _is_tool_result_only(content):
    return (isinstance(content, list) and len(content) > 0
            and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content))


def is_system_injected(text):
    head = text.lstrip()[:400]
    return any(m in head for m in SYSTEM_MARKERS)


def iter_messages(path):
    """yield dict(line, ts, text, shape, human)。human=False 为系统注入。"""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            if '"user"' not in line and '"assistant"' not in line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            # 形状 A：CC 原件
            if obj.get("type") in ("user", "assistant"):
                if obj.get("isSidechain"):
                    continue
                content = (obj.get("message") or {}).get("content")
                text = _text_of(content)
                ts = (obj.get("timestamp") or "")[:19].replace("T", " ")
                shape = "cc"
            # 形状 Codex：Paseo / Codex CLI rollout，消息嵌在 response_item.payload
            elif obj.get("type") == "response_item":
                payload = obj.get("payload") or {}
                if payload.get("type") != "message":
                    continue
                content = payload.get("content")
                text = _text_of(content)
                ts = (obj.get("timestamp") or "")[:19].replace("T", " ")
                shape = "codex"
            # 形状 B：S1 五件套
            elif obj.get("role") in ("user", "assistant"):
                # S1 把工具结果也写成 role=user（kind=tool_result），不滤掉会把
                # 人类消息数虚高一到两个数量级（2026-11-22：CC 16 条被数成 630 条）
                if obj.get("kind") in ("tool_result", "meta"):
                    continue
                text = _text_of(obj.get("content"))
                ts = (obj.get("t") or obj.get("timestamp") or "")[:19].replace("T", " ")
                shape = "s1"
            else:
                continue

            content = ((obj.get("message") or {}).get("content") if shape == "cc"
                       else (obj.get("payload") or {}).get("content") if shape == "codex"
                       else obj.get("content"))
            if _is_tool_result_only(content):
                continue
            text = text.strip()
            if not text:
                continue
            yield {
                "line": lineno,
                "ts": ts,
                "text": text,
                "shape": shape,
                "human": not is_system_injected(text),
                "role": (obj.get("type") if shape == "cc"
                         else (obj.get("payload") or {}).get("role") if shape == "codex"
                         else obj.get("role")),
            }


def user_messages(path, include_system=False):
    """只出用户消息；include_system=False 时滤掉系统注入。"""
    for m in iter_messages(path):
        if m["role"] != "user":
            continue
        if not include_system and not m["human"]:
            continue
        yield m


def stats(path):
    """返回 (human_user, injected_user, shape, longest_chars)。零输入 = (0,0,None,0)。"""
    human = injected = longest = 0
    shape = None
    for m in iter_messages(path):
        if m["role"] != "user":
            continue
        shape = shape or m["shape"]
        if m["human"]:
            human += 1
            longest = max(longest, len(m["text"]))
        else:
            injected += 1
    return human, injected, shape, longest

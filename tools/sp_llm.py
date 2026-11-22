#!/usr/bin/env python3
"""sp_llm —— 长任务 LLM 调用的唯一实现（超时 / 重试 / 杀进程组 / JSON 提取）。

为什么要有它（2026-11-22 复盘）：
同一段「调 claude -p，超时，取 stdout，抽 JSON」在本机被写了 **6 遍**
（youtb 的 summarize/assemble/admit/eval，kos-daily 的 rebind/mail/replyd），
每份都在自己处理超时——而其中一份（`subprocess.run(timeout=)`）会因孙进程占管道永久阻塞，
把批量卡死 20 分钟（断言 A567）。

判据：
  · 超时 → 杀**进程组**（setsid + killpg），返回 rc=124，调用方决定重试或降级
  · 三个编辑器同一套接口：claude / opencode / codex（codex 走 stdin）
  · `run_json` 自带「解析失败 → 把错误回灌给模型再试一次」

用法：
  from sp_llm import run, run_json
  r = run(prompt, timeout=180)                 # → Result(stdout, stderr, returncode)
  doc = run_json(prompt, validate=lambda d: (True, ""))
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = os.environ.get("SP_LLM_MODEL", "opencode-go/deepseek-v4.1-flash-b#high")
DEFAULT_TIMEOUT = 300
PROMPT_VER = 'v1'
SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
LOG = os.path.join(SSOT, 'logs', 'llm-runs.jsonl')
BUDGET_FILE = os.path.join(SSOT, 'logs', 'llm-budget.json')
BUDGET_DEFAULT = int(os.environ.get('ZB_LLM_BUDGET', '200'))


class BudgetExceeded(RuntimeError):
    pass


def _budget(n=1):
    today = datetime.date.today().isoformat()
    d = {}
    if os.path.exists(BUDGET_FILE):
        try:
            d = json.load(open(BUDGET_FILE, encoding='utf-8'))
        except Exception:
            d = {}
    used = d.get(today, 0)
    if used + n > BUDGET_DEFAULT:
        raise BudgetExceeded(f'今日预算 {BUDGET_DEFAULT} 次已用 {used}')
    d[today] = used + n
    os.makedirs(os.path.dirname(BUDGET_FILE), exist_ok=True)
    json.dump(d, open(BUDGET_FILE, 'w', encoding='utf-8'))
    return used + n


def _log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


@dataclass
class Result:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _argv(prompt: str, editor: str, model: str) -> tuple[list[str], str | None]:
    """→ (argv, stdin_prompt)。codex 只吃 stdin，其余吃 argv。

    `SP_LLM_FAKE_CMD` 仅供单测：直接替换 argv（可用 `bash -c \'sleep 30\'` 验超时杀组），
    不烧 token、不依赖编辑器安装。
    """
    fake = os.environ.get("SP_LLM_FAKE_CMD")
    if fake:
        import shlex
        return shlex.split(fake), None
    if editor == "opencode":
        cmd = ["opencode", "run", "--auto"]
        if model:
            cmd += ["--model", model]
        return cmd + [prompt], None
    if editor == "codex":
        return (["codex", "exec", "-s", "workspace-write",
                 "-c", "sandbox_workspace_write.network_access=true",
                 "--skip-git-repo-check", "-c", "approval_policy=never"], prompt)
    return ["claude", "-p", "--permission-mode", "bypassPermissions", prompt], None


def run(prompt: str, *, timeout: int = 300, cwd: str | Path | None = None,
        editor: str | None = None, model: str | None = None) -> Result:
    editor = editor or os.environ.get("SP_LLM_EDITOR") or os.environ.get("ZB_EDITOR", "claude")
    model = DEFAULT_MODEL if model is None else model
    argv, stdin = _argv(prompt, editor, model)
    cmd = argv + (["--cd", str(cwd)] if editor == "codex" and cwd else [])
    p = subprocess.Popen(
        cmd, cwd=str(cwd) if cwd and editor != "codex" else None,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,           # ← 关键：自成进程组，超时才能整组杀
    )
    try:
        out, err = p.communicate(input=stdin, timeout=timeout)
        return Result(out or "", err or "", p.returncode)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            p.kill()
        try:
            out, err = p.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        return Result(out or "", (err or "") + f"\n[sp_llm] timeout {timeout}s", 124)


def run_llm(prompt, schema_path=None, model=None, timeout=DEFAULT_TIMEOUT, retries=1, tag=''):
    """兼容旧 API（2026-11-22）：`run_llm(prompt, schema_path, tag=..., model=...)`。

    新实现走 run_json（编辑器无关）；schema_path 只用来取 `required` 做**结构校验**，
    不再像旧版那样交给 codex 的 --output-schema 强约束。保留 ZB_LLM_MOCK 以便离线测试。
    """
    if os.environ.get('ZB_LLM_MOCK') == '1':
        raw = os.environ.get('ZB_LLM_MOCK_JSON', '{"candidates":[]}')
        return json.loads(raw)

    validate = None
    try:
        if schema_path and os.path.exists(str(schema_path)):
            schema = json.load(open(schema_path, encoding='utf-8'))
            required = schema.get('required') or []

            def validate(doc):
                if required and isinstance(doc, dict):
                    miss = [k for k in required if k not in doc]
                    return (not miss, f'缺字段 {miss}')
                return (True, '')
    except Exception:
        validate = None

    _budget(1)
    doc = run_json(prompt, validate=validate, retries=retries, timeout=timeout, model=model)
    if doc is None:
        raise RuntimeError(f'sp_llm.run_llm 失败（tag={tag}）')
    return doc


def run_text(prompt: str, **kw) -> str:
    r = run(prompt, **kw)
    return r.stdout


def extract_json(text: str) -> dict | list | None:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    m = re.search(r"\{.*\}|\[.*\]", s, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def run_json(prompt: str, *, validate=None, retries: int = 1, **kw):
    """跑一次并抽 JSON；不合格就把原因回灌再试（最多 retries 次）。

    validate(doc) -> (ok, why)。why 会写进下一轮提示词。
    """
    msg = prompt
    for attempt in range(retries + 1):
        r = run(msg, **kw)
        doc = extract_json(r.stdout)
        if doc is None:
            why = "上一轮没有输出可解析的 JSON"
        elif validate:
            ok, why = validate(doc)
            if ok:
                return doc
        else:
            return doc
        if attempt < retries:
            msg = prompt + f"\n\n**上一轮不合格：{why}**。只输出 JSON，严格按上面的结构。\n"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm.py --selftest\n  sp_llm.py --ping')
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--ping', action='store_true')
    ap.add_argument('--model', default=None)
    a = ap.parse_args(argv)
    if a.selftest:
        os.environ['ZB_LLM_MOCK'] = '1'
        os.environ['ZB_LLM_MOCK_JSON'] = json.dumps({'candidates': [
            {'claim': '阈值需按分布校准', 'type': 'insight', 'quote': '阈值必须校准', 'line': 3,
             'durability': 0.8, 'why': '可复用'}]}, ensure_ascii=False)
        d = run_llm('mock', os.path.join(SSOT, 'schemas/candidate.json'), tag='selftest')
        ok = d['candidates'][0]['claim'] == '阈值需按分布校准'
        print(f'worker 自测:{"✅" if ok else "❌"} {d}')
        return 0 if ok else 2
    if a.ping:
        d = run_llm('Return ok=true and note="worker alive".',
                    os.path.join(SSOT, 'schemas/candidate.json'), model=a.model, tag='ping')
        print(json.dumps(d, ensure_ascii=False))
        return 0
    ap.print_help()
    return 1


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except BudgetExceeded as e:
        print(f'❌ {e}', file=sys.stderr)
        sys.exit(2)

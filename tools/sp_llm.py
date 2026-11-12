#!/usr/bin/env python3
"""sp_llm · LLM worker(基于 `codex exec --output-schema`)

设计:drafts/full-dump-design-2026-10-31.md §4.6
铁律:只产候选/草稿;**永不写正本**。所有调用带 run_id/model/prompt_ver 落 logs/llm-runs.jsonl。

用法:
  sp_llm.py --selftest                 # 不联网,mock 校验
  sp_llm.py --ping                     # 真实一次最小调用(约 8k tok)
  from sp_llm import run_llm           # 代码内调用
"""
import argparse, datetime, json, os, subprocess, sys, tempfile, time, uuid

SSOT = os.path.expanduser('~/ssot')
LOG = os.path.join(SSOT, 'logs', 'llm-runs.jsonl')
BUDGET_FILE = os.path.join(SSOT, 'logs', '.llm-budget.json')
PROMPT_VER = 'v1'
DEFAULT_TIMEOUT = 240
BUDGET_DEFAULT = int(os.environ.get('ZB_LLM_BUDGET', '60'))


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


def run_llm(prompt, schema_path, model=None, timeout=DEFAULT_TIMEOUT, retries=1, tag=''):
    """→ dict(按 schema 约束的模型输出)。失败抛 RuntimeError。"""
    run_id = uuid.uuid4().hex[:12]
    if os.environ.get('ZB_LLM_MOCK') == '1':
        raw = os.environ.get('ZB_LLM_MOCK_JSON', '{"candidates":[]}')
        _log({'run_id': run_id, 'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
              'tag': tag, 'mock': True, 'prompt_ver': PROMPT_VER, 'ok': True, 'ms': 0, 'tokens': 0})
        return json.loads(raw)

    _budget(1)
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
            out_path = tf.name
        cmd = ['codex', 'exec', '--ephemeral', '--skip-git-repo-check', '-s', 'read-only',
               '--output-schema', schema_path, '-o', out_path]
        if model:
            cmd += ['-m', model]
        cmd += ['-']
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
            ms = int((time.time() - t0) * 1000)
            txt = open(out_path, encoding='utf-8').read().strip() if os.path.exists(out_path) else ''
            tokens = 0
            import re as _re
            m = _re.search(r'tokens used\s*\n?\s*([\d,]+)', r.stderr or '', _re.I)
            if m:
                tokens = int(m.group(1).replace(',', ''))
            if r.returncode == 0 and txt:
                data = json.loads(txt)
                _log({'run_id': run_id, 'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                      'tag': tag, 'model': model or 'default', 'prompt_ver': PROMPT_VER,
                      'ok': True, 'ms': ms, 'tokens': tokens, 'attempt': attempt})
                return data
            last = f'rc={r.returncode} out={txt[:120]} err={(r.stderr or "")[-200:]}'
        except Exception as e:  # noqa: BLE001
            last = f'{type(e).__name__}: {e}'
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass
        time.sleep(2 + attempt * 3)
    _log({'run_id': run_id, 'ts': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
          'tag': tag, 'model': model or 'default', 'prompt_ver': PROMPT_VER, 'ok': False, 'error': last})
    raise RuntimeError(f'llm 调用失败: {last}')


def selftest():
    os.environ['ZB_LLM_MOCK'] = '1'
    os.environ['ZB_LLM_MOCK_JSON'] = json.dumps({'candidates': [
        {'claim': '阈值需按分布校准', 'type': 'insight', 'quote': '阈值必须校准', 'line': 3,
         'durability': 0.8, 'why': '可复用'}]}, ensure_ascii=False)
    d = run_llm('mock', os.path.join(SSOT, 'schemas/candidate.json'), tag='selftest')
    ok = d['candidates'][0]['claim'] == '阈值需按分布校准'
    print(f'worker 自测:{"✅" if ok else "❌"} {d}')
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_llm.py --selftest\n  sp_llm.py --ping',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--ping', action='store_true')
    ap.add_argument('--model', default=None)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.ping:
        d = run_llm('Return ok=true and note="worker alive".',
                    os.path.join(SSOT, 'schemas/candidate.json'), model=a.model, tag='ping')
        print(json.dumps(d, ensure_ascii=False))
        return 0
    ap.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main() or 0)

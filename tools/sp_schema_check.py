#!/usr/bin/env python3
"""sp_schema_check · 只读扫描实例数据契约与产物 schema 分布(不写盘)

用法:
  python3 tools/sp_schema_check.py            # 人类可读摘要
  python3 tools/sp_schema_check.py --json     # 机读(供 ssot_check/迁移器)
退出码:0=全部一致;1=有漂移(需要 sp_migrate)
"""
import argparse, glob, json, os, sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
CONTRACT = os.path.join(SSOT, 'profile', 'contract.json')


def load_contract():
    try:
        return json.load(open(CONTRACT, encoding='utf-8'))
    except Exception:
        return {}


def dist(values):
    out = {}
    for v in values:
        k = str(v)
        out[k] = out.get(k, 0) + 1
    return out


def scan():
    c = load_contract()
    target = int(c.get('contract', 0) or 0)
    res = {'contract': target, 'artifacts': {}, 'drift': []}

    # S1 meta.json
    metas = glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*', 'meta.json'))
    vers = []
    for m in metas:
        try:
            vers.append(json.load(open(m, encoding='utf-8')).get('schema'))
        except Exception:
            vers.append('bad')
    res['artifacts']['s1_meta'] = {'count': len(metas), 'schema': dist(vers)}
    if target and any(v != target for v in vers):
        res['drift'].append(f"S1 meta.json: {dist(vers)} → 期望 {target}")

    # 账本
    led = os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')
    lv = []
    if os.path.exists(led):
        for ln in open(led, encoding='utf-8', errors='replace'):
            ln = ln.strip()
            if not ln:
                continue
            try:
                lv.append(json.loads(ln).get('schema'))
            except Exception:
                lv.append('bad')
    res['artifacts']['ledger'] = {'count': len(lv), 'schema': dist(lv)}
    if target and any(v != target for v in lv):
        res['drift'].append(f"ledger: {dist(lv)} → 期望 {target}")

    # BUILD.json
    b = os.path.join(SSOT, 'S2-index', 'semantic', 'BUILD.json')
    bv = None
    if os.path.exists(b):
        try:
            bv = json.load(open(b, encoding='utf-8')).get('schema')
        except Exception:
            bv = 'bad'
    res['artifacts']['build'] = {'count': 1 if bv is not None else 0, 'schema': str(bv)}
    if target and bv is not None and bv != target:
        res['drift'].append(f"BUILD.json: {bv} → 期望 {target}")

    return res


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_schema_check.py\n  sp_schema_check.py --json',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    r = scan()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f'契约版本 {r["contract"]}')
        for k, v in r['artifacts'].items():
            print(f'  {k}: {v["count"]} 份 · schema 分布 {v["schema"]}')
        if r['drift']:
            print('⚠ 漂移:')
            for d in r['drift']:
                print('  -', d)
        else:
            print('✅ 全部一致')
    return 0 if not r['drift'] else 1


if __name__ == '__main__':
    sys.exit(main() or 0)

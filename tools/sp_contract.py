#!/usr/bin/env python3
"""sp_contract · 实例数据契约守卫(供各工具在启动时调用)

规则:
  实例契约 < 工具要求  → 写工具拒绝运行;读工具警告后继续
  实例契约 > 工具支持  → 警告(工具可能看不懂新字段),只读建议
"""
import json, os, sys

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
CONTRACT = os.path.join(SSOT, 'profile', 'contract.json')
TOOL_CONTRACT = 2          # 本版工具支持的契约号


def contract_num():
    try:
        return int(json.load(open(CONTRACT, encoding='utf-8')).get('contract', 0))
    except Exception:
        return 0


def guard(name, write=True, need=TOOL_CONTRACT):
    """→ True 可继续;False 应退出"""
    cur = contract_num()
    if cur == 0:
        print(f'⚠ {name}: 未找到数据契约(profile/contract.json)——按旧实例处理,只读或先跑 sp_migrate',
              file=sys.stderr)
        return not write
    if cur < need:
        msg = f'{name}: 实例契约 v{cur} < 工具要求 v{need} —— 先跑 python3 tools/sp_migrate.py --to {need} --apply'
        print(msg, file=sys.stderr)
        return False
    if cur > TOOL_CONTRACT:
        print(f'⚠ {name}: 实例契约 v{cur} 高于工具支持 v{TOOL_CONTRACT}——建议只读,先升级工具',
              file=sys.stderr)
    return True

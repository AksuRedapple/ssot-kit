#!/bin/bash
# conf 归一化验收(2026-11-06):四前缀 + 常见同义词 + 决定/用户令不计置信度
set -u
export KIT="$(cd "$(dirname "$0")/../.." && pwd)"; fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3(期望 $2,得 $1)"; fail=1; }; }
out=$(python3 - <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.environ['KIT'], 'tools'))
from ssot_check import normalize_conf as n
cases = {
 '实测': '实测', '源码+实测': '实测', '设备实测': '实测',
 '代码/单测实测，**设备验收待补**': '实测',
 '推断': '推断', '推算': '推算', '待核': '待核',
 '决定': None, '用户令（aio-ops §9.1）': None, 'unknown': None,
}
bad = {k:(n(k),v) for k,v in cases.items() if n(k)!=v}
print('ok' if not bad else bad)
PY
)
chk "$out" "ok" "10 个映射全对"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

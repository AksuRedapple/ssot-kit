#!/bin/bash
# kit 侧测试入口（相对路径，不依赖 ~/ssot）
# 发现规则：*_test.sh → bash；test_*.py → python3（S11：新测试必须真的被执行）
# 退出码协议：0=PASS；77=SKIP（显性跳过）；其它=FAIL（A562）
set -u
D="$(cd "$(dirname "$0")" && pwd)"; fail=0
run_one() {
  local t="$1" rc
  bash "$t" >/tmp/kit-test.out 2>&1; rc=$?
  if [ "$rc" -eq 77 ]; then echo "↷ $(basename "$t") (skip)"
  elif [ "$rc" -ne 0 ]; then echo "✗ $(basename "$t")"; tail -20 /tmp/kit-test.out; fail=1; fi
}
run_py() {
  local t="$1" rc
  python3 "$t" >/tmp/kit-test.out 2>&1; rc=$?
  if [ "$rc" -eq 77 ]; then echo "↷ $(basename "$t") (skip)"
  elif [ "$rc" -ne 0 ]; then echo "✗ $(basename "$t")"; tail -20 /tmp/kit-test.out; fail=1; fi
}
for t in "$D"/*_test.sh; do [ -e "$t" ] || continue; run_one "$t"; done
for t in "$D"/test_*.py; do [ -e "$t" ] || continue; run_py "$t"; done
[ $fail -eq 0 ] && echo "kit tests: 全部通过" || echo "kit tests: 有失败"
exit $fail

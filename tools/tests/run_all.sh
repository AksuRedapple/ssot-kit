#!/bin/bash
# kit 侧测试入口（相对路径，不依赖 ~/ssot）
# 发现规则：*_test.sh → bash；test_*.py → python3（S11：新测试必须真的被执行）
set -u
D="$(cd "$(dirname "$0")" && pwd)"; fail=0
for t in "$D"/*_test.sh; do
  [ -e "$t" ] || continue
  bash "$t" >/tmp/kit-test.out 2>&1 || { echo "✗ $(basename "$t")"; tail -20 /tmp/kit-test.out; fail=1; }
done
for t in "$D"/test_*.py; do
  [ -e "$t" ] || continue
  python3 "$t" >/tmp/kit-test.out 2>&1 || { echo "✗ $(basename "$t")"; tail -20 /tmp/kit-test.out; fail=1; }
done
[ $fail -eq 0 ] && echo "kit tests: 全部通过" || echo "kit tests: 有失败"
exit $fail

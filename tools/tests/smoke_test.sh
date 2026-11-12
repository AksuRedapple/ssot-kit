#!/bin/bash
# 随包冒烟(无个人路径):隔离 HOME 跑 install → update → ssot_check → 迁移
set -u
KIT="$(cd "$(dirname "$0")/../.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0; chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3"; fail=1; }; }
export HOME="$T"
bash "$KIT/tools/install/setup.sh" --root "$T/ssot" --skills-dir "$T/skills" >/dev/null 2>&1
chk "$([ -f "$T/ssot/tools/ssot_check.py" ] && echo y)" "y" "setup 拷贝框架件"
bash "$KIT/tools/install/update.sh" --root "$T/ssot" --skip-pull >/dev/null 2>&1
chk "$(python3 "$T/ssot/tools/ssot_check.py" 2>/dev/null | grep -c '完成 ==（健康）')" "1" "新装体检健康"
python3 "$T/ssot/tools/sp_migrate.py" --to current --apply >/dev/null 2>&1
chk "$?" "0" "迁移 --to current"
[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"; exit $fail

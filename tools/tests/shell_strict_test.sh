#!/bin/bash
# 回归：非测试 shell 必须显式声明失败模式（set -e），或登记为 fail-open 例外。
#
# 背景（0.24.0）：审计发现 6 个 shell 缺 set -e，但其中 hooks 是**故意** fail-open——
# 加 set -e 会让 `[ -f X ] && exit 0` 这类写法在文件不存在时直接终止 hook。
# 所以不是一刀切：门禁/值守要 fail loud，hook 要 fail open 且写清理由。
set -u
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3(期望 $2,得 $1)"; fail=1; }; }

# fail-open 例外（必须同时有注释说明）
ALLOW="hooks/session-start.sh hooks/stop-draft.sh hooks/user-prompt-retrieval.sh"

has_e(){ grep -qE '^set -[a-zA-Z]*e' "$1"; }

for f in "$KIT"/scripts/*.sh "$KIT"/tools/*.sh "$KIT"/hooks/*.sh; do
  [ -e "$f" ] || continue
  rel="${f#$KIT/}"
  case " $ALLOW " in
    *" $rel "*)
      has_e "$f" && { echo "  FAIL $rel 在 fail-open 例外里却设了 set -e"; fail=1; }
      grep -q '不设 set -e' "$f" || { echo "  FAIL $rel 缺少 fail-open 说明注释"; fail=1; }
      ;;
    *)
      has_e "$f" || { echo "  FAIL $rel 缺 set -e"; fail=1; }
      ;;
  esac
done
echo "  ok   扫描完成（例外：$ALLOW）"

# 例外清单本身也要收敛：新增例外必须改这里并说明理由
n=$(echo $ALLOW | wc -w | tr -d ' ')
chk "$n" "3" "fail-open 例外数 = 3"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

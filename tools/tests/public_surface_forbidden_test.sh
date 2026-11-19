#!/usr/bin/env bash
# 回归：public-audit 必须拒绝 golden 基线/退休表等实例数据进入 kit 根（2026-11-18）
set -u
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

cp -a "$KIT/." "$T/kit/" 2>/dev/null || true
mkdir -p "$T/kit/profile"
printf '{"queries":[{"query":"private"}]}\n' > "$T/kit/profile/golden-baseline.json"
out=$(bash "$T/kit/scripts/public-audit.sh" 2>&1); rc=$?
chk "$rc" "1" "基线存在时 audit rc=1"
n=$(printf '%s' "$out" | grep -c 'golden baseline')
[ "$n" -ge 1 ] && echo "  ok   报出 golden baseline" || { echo "  FAIL 未报出 golden baseline"; fail=1; }

rm -f "$T/kit/profile/golden-baseline.json"
out=$(bash "$T/kit/scripts/public-audit.sh" 2>&1); rc=$?
chk "$rc" "0" "移除后 audit rc=0"

# 本地工具状态目录（.omq）不参与公开面
mkdir -p "$T/kit/.omq/state"
printf '{"p":"%s"}\n' "/Users/${USER}/private" > "$T/kit/.omq/state/x.json"
out=$(bash "$T/kit/scripts/public-audit.sh" 2>&1); rc=$?
chk "$rc" "0" ".omq 本地状态不误报"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

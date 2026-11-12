#!/bin/bash
# 线页内容漂移验收(2026-11-06):线页版本 vs 真源 JSON
set -u
export KIT="$(cd "$(dirname "$0")/../.." && pwd)"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3(期望 $2,得 $1)"; fail=1; }; }
mkdir -p "$T/lines" "$T/profile"
cat > "$T/lines/x.md" <<'MD'
# x
- **版本**：线上 **1.0.0**（`versionCode=1`）
MD
cat > "$T/source.json" <<'JSON'
{"apps":{"X":{"versionName":"1.0.0","versionCode":1}}}
JSON
cat > "$T/profile/line_sources.json" <<JSON
{"x":{"file":"lines/x.md","kind":"json","source":"$T/source.json","app":"X","field":"versionName","pattern":"线上\\\\s*\\\\*{0,2}(\\\\d+\\\\.\\\\d+\\\\.\\\\d+)","code_field":"versionCode","code_pattern":"versionCode=(\\\\d+)"}}
JSON
out=$(python3 - "$T" <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.environ['KIT'], 'tools'))
import ssot_check
print(len(ssot_check.line_drift(sys.argv[1])))
PY
)
chk "$out" "0" "一致时无漂移"

cat > "$T/source.json" <<'JSON'
{"apps":{"X":{"versionName":"2.0.0","versionCode":2}}}
JSON
out=$(python3 - "$T" <<'PY'
import sys, os
sys.path.insert(0, os.path.join(os.environ['KIT'], 'tools'))
import ssot_check
print(len(ssot_check.line_drift(sys.argv[1])))
PY
)
chk "$out" "2" "版本+vc 两处漂移"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

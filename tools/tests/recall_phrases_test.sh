#!/usr/bin/env bash
# 回归：回忆触发词覆盖真实问法，且 hook/插件 fallback 与单一真源同步（2026-11-18）
set -u
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3（期望 $2，得 $1）"; fail=1; }; }

out=$(python3 - "$KIT" <<'PY'
import json, re, sys
from pathlib import Path
kit = Path(sys.argv[1])
rx = re.compile(json.loads((kit/'tools/recall-phrases.json').read_text(encoding='utf-8'))['regex'])
pos = ["不知道还有没有历史对话记录", "帮我查一下历史", "这个之前用过吗", "还记得上次那个方案吗"]
neg = ["这个库有没有记录这个字段", "帮我看看这个函数怎么改", "今天天气怎么样"]
bad = [s for s in pos if not rx.search(s)] + [s for s in neg if rx.search(s)]
print('bad=' + ('none' if not bad else '|'.join(bad)))
# hook 内嵌 fallback == JSON regex
txt = (kit/'hooks/user-prompt-retrieval.sh').read_text(encoding='utf-8')
m = re.search(r'^RX="(.*)"$', txt, re.M)
print('hook_same=' + str(bool(m) and m.group(1) == rx.pattern))
ts = (kit/'hooks/pi/ssot-boot.ts').read_text(encoding='utf-8')
print('ts_synced=' + str('历史(会话|记录|里|对话)' in ts))
PY
)
chk "$(printf '%s\n' "$out" | grep '^bad=' | cut -d= -f2)" "none" "正例命中 / 反例不误触"
chk "$(printf '%s\n' "$out" | grep '^hook_same=' | cut -d= -f2)" "True" "hook fallback 与 JSON 一致"
chk "$(printf '%s\n' "$out" | grep '^ts_synced=' | cut -d= -f2)" "True" "pi 插件 fallback 已同步"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail

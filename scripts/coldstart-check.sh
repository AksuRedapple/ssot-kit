#!/usr/bin/env bash
# coldstart-check · 冷启动/升级后的 60 秒自检（只读，不改实例）
#
# 用法：bash scripts/coldstart-check.sh [--strict]
#   --strict  把“警告”也当失败（CI/发版前用）
#
# 检查四段：
#   1 解释器：python3 / SSOT_PY 是否能 import numpy
#   2 指令：START.md / profile/harness-boot.md 引用的 tools/* 是否存在、且不在 tools/legacy/
#   3 索引：active S2 索引是否存在；legacy 库是否还在（双栈提示）
#   4 预算：MEMORY.md 体积、线页过期数、已结/搁置状态词
#
# 退出码：0=通过（可带警告）；1=有阻断项
set -euo pipefail

ROOT="${SSOT_ROOT:-$HOME/ssot}"
STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1
fail=0
warn=0
ok(){ echo "  ok   $*"; }
bad(){ echo "  FAIL $*" >&2; fail=$((fail+1)); }
note(){ echo "  ⚠    $*" >&2; warn=$((warn+1)); }

echo "== coldstart-check · $ROOT =="

# 1) 解释器
PY="${SSOT_PY:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  bad "解释器不存在：$PY（设 SSOT_PY 指向带 numpy 的 python）"
elif "$PY" -c 'import sys, numpy; print(sys.version.split()[0], numpy.__version__)' >/tmp/.ssot-py 2>/dev/null; then
  ok "解释器 $PY：$(cat /tmp/.ssot-py)（numpy 可用）"
else
  bad "解释器 $PY 缺 numpy；语义检索会失败。export SSOT_PY=/path/to/python"
fi
rm -f /tmp/.ssot-py

# 2) 开机/START 引用的工具
for f in "$ROOT/profile/harness-boot.md" "$ROOT/START.md"; do
  [ -f "$f" ] || continue
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    case "$rel" in
      tools/legacy/*) bad "$(basename "$f") 引用 legacy 工具：$rel（改用 sp_semantic/sp_index）" ;;
      *) if [ ! -e "$ROOT/$rel" ]; then bad "$(basename "$f") 引用不存在的工具：$rel"; fi ;;
    esac
  # 只查实例内 tools/ 的引用；study-infra/scripts/... 属于其他仓库，不在此判
  done < <(grep -oE 'tools/[A-Za-z0-9_./-]+\.(py|sh)' "$f" 2>/dev/null | sort -u)
done

# 3) 索引：active vs legacy
BUILD="$ROOT/S2-index/semantic/BUILD.json"
ACT="$ROOT/S2-index/semantic/active.json"
if [ -f "$ACT" ]; then
  VER=$("$PY" -c "import json;print(json.load(open('$ACT')).get('version',''))" 2>/dev/null || true)
  [ -n "$VER" ] && [ -f "$ROOT/S2-index/semantic/versions/$VER/BUILD.json" ] && BUILD="$ROOT/S2-index/semantic/versions/$VER/BUILD.json"
fi
if [ -f "$BUILD" ]; then
  "$PY" - "$BUILD" <<'PY' 2>/dev/null && ok "S2 active 索引存在" || note "S2 BUILD.json 读不出块数"
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8'))
print(f"       chunks={d.get('chunks','?')} built_at={d.get('built_at','?')} commit={d.get('commit','-')}")
PY
else
  note "没有 S2 索引（语义检索不可用；先跑 sp_index.py --incremental）"
fi
for old in "$ROOT/kb-index/BUILD.json" "$ROOT/S2-index/kb/BUILD.json"; do
  if [ -f "$old" ]; then
    note "发现 legacy 索引：${old#$ROOT/}（确认冷启动是否还在用它）"
  fi
done

# 4) 预算：MEMORY / 线页 / 状态词
MEM="$HOME/.qoder/memory/MEMORY.md"
if [ -f "$MEM" ]; then
  sz=$(wc -c < "$MEM" | tr -d ' ' || true)
  if [ "$sz" -gt 25000 ]; then bad "MEMORY.md ${sz}B 超过 25KB 硬限（sp_compile --mem 会拒切）";
  elif [ "$sz" -gt 24000 ]; then note "MEMORY.md ${sz}B 接近 24KB 告警线";
  else ok "MEMORY.md ${sz}B（<24KB）"; fi
fi
if [ -d "$ROOT/lines" ]; then
  stale=$(find "$ROOT/lines" -maxdepth 1 -name '*.md' -mtime +30 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$stale" -gt 0 ]; then note "线页过期 ${stale} 条（>30 天）"; else ok "线页全部新鲜"; fi
  hit=$(grep -lE '^> 状态:.*(已结|搁置)' "$ROOT"/lines/*.md 2>/dev/null | wc -l | tr -d ' ' || true)
  if [ "$hit" -gt 0 ]; then
    note "有 ${hit} 条线页使用 已结/搁置；sp_line_status 当前会映射成“活跃”，先跑 --dry-run"
  fi
fi

echo "== 结果：$([ "$fail" -eq 0 ] && echo 通过 || echo 失败)（阻断 $fail / 警告 $warn） =="
if [ "$STRICT" = "1" ] && [ "$warn" -gt 0 ]; then
  exit 1
fi
if [ "$fail" -ne 0 ]; then
  exit 1
fi
exit 0

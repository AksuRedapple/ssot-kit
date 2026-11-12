#!/usr/bin/env bash
# 发布前闸门:影子实例 dogfooding(隔离 HOME,不碰本机 ~/ssot)
# 用法: bash scripts/preflight.sh [--keep] [--quiet]
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
KEEP=0; QUIET=0
for a in "$@"; do case "$a" in --keep) KEEP=1;; --quiet) QUIET=1;; esac; done
TMP="$(mktemp -d)"; trap '[ "$KEEP" = 1 ] && echo "保留: $TMP" || rm -rf "$TMP"' EXIT
log(){ [ "$QUIET" = 1 ] || echo "▸ $*"; }
fail(){ echo "❌ preflight: $*" >&2; exit 1; }

log "影子 HOME=$TMP"
mkdir -p "$TMP/bin" "$TMP/ssot" "$TMP/skills"
# 2026-11-06：测当前工作树，不是已提交的 HEAD——发布前改动尚未 commit，
# 用 git clone 会测到旧版本，闸门形同虚设。
mkdir -p "$TMP/kit"
cp -a "$KIT/." "$TMP/kit/" || fail "复制工作树失败"
export HOME="$TMP"
log "setup"
bash "$TMP/kit/tools/install/setup.sh" --root "$TMP/ssot" --skills-dir "$TMP/skills" >/dev/null || fail "setup 失败"
log "update --skip-pull"
bash "$TMP/kit/tools/install/update.sh" --root "$TMP/ssot" --skip-pull >/dev/null || fail "update 失败"
log "ssot_check"
python3 "$TMP/ssot/tools/ssot_check.py" > "$TMP/check.log" 2>&1 || fail "ssot_check 非零"
grep -q "完成 ==（健康）" "$TMP/check.log" || fail "ssot_check 未报健康"
log "sp_migrate --to current --apply"
python3 "$TMP/ssot/tools/sp_migrate.py" --to current --apply >/dev/null 2>&1 || fail "迁移失败"
python3 "$TMP/ssot/tools/sp_schema_check.py" >/dev/null || fail "迁移后 schema 不一致"
log "迁移后再体检"
python3 "$TMP/ssot/tools/ssot_check.py" | grep -q "完成 ==（健康）" || fail "迁移后体检不健康"
echo "✅ preflight 全绿（影子实例可装/可升/可迁）"

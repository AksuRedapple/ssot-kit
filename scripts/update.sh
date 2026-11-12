#!/usr/bin/env bash
# 兼容旧路径的薄包装：真正实现已收敛到 tools/install/
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$KIT/tools/install/update.sh" "$@"

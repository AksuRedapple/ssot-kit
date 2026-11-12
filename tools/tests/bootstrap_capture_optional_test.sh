#!/bin/bash
# 公开 kit 不随包 capture 扩展；只有两个扩展文件同时存在时才规划 capture。
set -eu
KIT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

check () {
  HOME="$1" python3 - "$KIT" "$2" <<'PY'
import importlib.util
import pathlib
import sys

kit = pathlib.Path(sys.argv[1])
expected = sys.argv[2] == "yes"
spec = importlib.util.spec_from_file_location("sp_bootstrap", kit / "tools" / "sp_bootstrap.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.CAPTURE_AVAILABLE is expected
assert ("capture" in mod.PHASES) is expected
print("capture optional: ok")
PY
}

mkdir -p "$T/public"
check "$T/public" no

mkdir -p "$T/full/ssot/tools"
: > "$T/full/ssot/tools/sp_sweep.py"
: > "$T/full/ssot/tools/sp_capture.py"
check "$T/full" yes

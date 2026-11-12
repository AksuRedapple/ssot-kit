#!/usr/bin/env bash
# Release metadata gate: VERSION / CHANGELOG / CAPABILITIES must agree.
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KIT"

version="$(tr -d '[:space:]' < VERSION)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "❌ VERSION is not semver: $version" >&2
  exit 1
}

grep -qF '## [Unreleased]' CHANGELOG.md || {
  echo "❌ CHANGELOG.md is missing [Unreleased]" >&2
  exit 1
}

first="$(grep -m1 '^## \[[0-9]' CHANGELOG.md || true)"
[[ "$first" == "## [$version] - "* ]] || {
  echo "❌ newest CHANGELOG entry is not [$version] - YYYY-MM-DD" >&2
  echo "   got: ${first:-<none>}" >&2
  exit 1
}

grep -qF "# kit 能力清单（v$version ·" CAPABILITIES.md || {
  echo "❌ CAPABILITIES.md header does not declare v$version" >&2
  exit 1
}

bad="$(grep -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\] - ' CHANGELOG.md |
  grep -Ev '^## \[[0-9]+\.[0-9]+\.[0-9]+\] - [0-9]{4}-[0-9]{2}-[0-9]{2}( — .+)?$' || true)"
if [ -n "$bad" ]; then
  echo "❌ malformed CHANGELOG headings:" >&2
  printf '%s\n' "$bad" >&2
  exit 1
fi

dups="$(grep -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\] - ' CHANGELOG.md | sort | uniq -d || true)"
if [ -n "$dups" ]; then
  echo "❌ duplicate CHANGELOG version headings:" >&2
  printf '%s\n' "$dups" >&2
  exit 1
fi

echo "✅ release metadata: v$version / CHANGELOG / CAPABILITIES aligned"

#!/usr/bin/env bash
# Public-surface gate: credentials, machine-local data, private networks, and
# relative Markdown links must stay clean in every push and pull request.
set -euo pipefail

KIT="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$KIT" <<'PY'
from pathlib import Path
from urllib.parse import unquote
import re
import sys

root = Path(sys.argv[1]).resolve()
skip_dirs = {".git", "__pycache__", ".venv"}
files = []
for path in root.rglob("*"):
    if not path.is_file() or any(part in skip_dirs for part in path.parts):
        continue
    if path.suffix in {".pyc", ".db"} or path.name == ".DS_Store":
        continue
    files.append(path)

sensitive = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "OpenAI-style key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Hugging Face token": re.compile(r"hf_[A-Za-z0-9]{30,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "personal absolute path": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    "private IPv4": re.compile(
        r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])"
    ),
}

issues = []
texts = {}
for path in files:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    texts[path] = text
    rel = path.relative_to(root)
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in sensitive.items():
            if pattern.search(line):
                issues.append(f"{rel}:{lineno}: {label}")

link_rx = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
scheme_rx = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
tool_rx = re.compile(r"\b(?:(?:sp|kb)_[A-Za-z0-9_]+|scan_sessions|ssot_check)\.py\b")
known_basenames = {path.name for path in files}
for path, text in texts.items():
    if path.suffix.lower() != ".md":
        continue
    rel = path.relative_to(root)
    # Changelog entries may describe extensions that intentionally do not ship.
    # Current-facing docs must still only name tools present in this distribution.
    if path.name != "CHANGELOG.md":
        for name in tool_rx.findall(text):
            if name not in known_basenames:
                issues.append(f"{rel}: missing tool reference -> {name}")
    for match in link_rx.finditer(text):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]
        if not target or target.startswith("#") or scheme_rx.match(target):
            continue
        clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if not clean:
            continue
        resolved = (root / clean.lstrip("/")) if clean.startswith("/") else (path.parent / clean)
        if not resolved.exists():
            issues.append(f"{rel}: broken relative link -> {target}")

if issues:
    print("public audit failed:", file=sys.stderr)
    for issue in sorted(set(issues)):
        print(f"  - {issue}", file=sys.stderr)
    raise SystemExit(1)

print(f"public audit: clean ({len(files)} files; secrets, machine paths, private IPs, links, tool refs)")
PY

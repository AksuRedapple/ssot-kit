# Architecture

> Design goals: harness-neutral, content stays local, upgrades never touch your content.
> Chinese version: [ARCHITECTURE.md](ARCHITECTURE.md) (authoritative).

## Layers of ownership

| Layer | Where | Rule | Examples |
|---|---|---|---|
| **Framework** | repo `tools/`, `skills/`, `hooks/` | overwritten on upgrade | `sp_compile.py`, ssmap skill |
| **Template** | repo `instance/` → `~/ssot/` | fill gaps only | `START.md`, `registry.md`, line template |
| **Content** | `~/ssot/` (lines/knowledge/inbox/sessions/evidence) | **never touched** | your ledger, knowledge, inbox |

Corollary: to keep a custom framework file, change the upstream (open an issue), don't edit your local copy.

## Components (v0.8)

| Component | Carrier | Purpose |
|---|---|---|
| Session ledger | registry + lines/ + ssmap skill | three opening questions / one-line close |
| Knowledge base | knowledge/ + inbox/ | distillation (fact: source / decision: owner) |
| Thin-shell compile | `tools/sp_compile.py` | canonical source → tiny agent-memory entry (`--target` for non-Qoder) |
| Semantic recall | `tools/sp_index.py` + `sp_semantic.py` + `serve_embed.sh` | search by meaning (local model, optional) |
| Session inventory | `tools/scan_sessions.py` | existing sessions → TSV |
| Self-check | `tools/ssot_check.py` | ledger / inbox / index / coverage health |
| Upgrade | `tools/install/update.sh` (+ `scripts/update.sh` wrapper) | one command |

## Deployment shapes

**Single machine (default)**: clone → `tools/install/setup.sh` → you are the owner; no upstream/downstream permission rules.

**Multi-machine (optional)**: an upstream fork; downstream machines `git pull` read-only. "Pull only" is a *distribution convention* in that mode, not a requirement of the project.

## Roadmap

- [x] Open-source surface: MIT license, English README, positioning
- [x] Session transcripts in the index (four sources → S1 → semantic index)
- [x] Steward (launchd freshness/inventory) for downstream
- [x] Hook installation (`scripts/install-hooks.sh`)
- [x] 10-minute quick start (`docs/QUICKSTART.md`)
- [ ] Demo material / method article
- [ ] English docs fully aligned with Chinese

# SETUP · First install (run by an agent)

> Goal: deploy the knowledge-governance system on this machine (instance at `~/ssot`, skills, session inventory).
> Execute step by step; stop and confirm with the user at the marked checkpoints.

## Rules (read first)

- This repo is a **reference implementation**: don't push your personal content into it (fork if you want to change it); issues/PRs welcome.
- Artifacts live in `~/ssot/` and your harness's skills directory; **never send content anywhere**.
- Network: if GitHub is slow, use your machine's existing proxy settings; **do not bypass organizational or device network policy**.
- Do not modify or delete existing files; the template layer only fills gaps.

## Prerequisites

- macOS + `python3` ≥3.10 + `git` + `numpy` (`pip install numpy`).
- Platforms: macOS ✅ tested; Linux works (replace launchd with `systemd --user`); Windows untested.

## Steps

### 1. Get the repo

```bash
KIT="${SSOT_KIT_DIR:-$HOME/ssot-kit}"
git clone https://github.com/AksuRedapple/ssot-kit "$KIT" 2>/dev/null || (cd "$KIT" && git pull)
```
The resolved path is written to `~/ssot/profile/.kit-path`; templates and skills look the repo up through it.

### 2. Create the instance + install skills

```bash
KIT="${SSOT_KIT_DIR:-$HOME/ssot-kit}"
bash "$KIT/tools/install/setup.sh" --root "$HOME/ssot"
```
→ creates the skeleton (`START.md`, `lines/`, `sessions/`, `knowledge/`, `inbox/`, `profile/`, `tools/`) and installs skills into the first detected harness directory (`~/.qoder/skills`, `~/.dsh/skills`, `~/.claude/skills`, `~/.codex/skills`, opencode).

### 3. Install the boot block (replaces your agent memory entry)

> ⚠️ **This step replaces your current agent memory entry** (default `~/.qoder/memory/MEMORY.md`). The previous version is backed up under `~/ssot/compile/`; read [docs/UNINSTALL.md](docs/UNINSTALL.md) before running.
> Not using Qoder? Point `--target` at your harness entry (see §6).

```bash
python3 ~/ssot/tools/sp_compile.py --mem --deploy
```
**Do not hand-edit the entry**; change `profile/harness-boot.md` and re-compile instead.

**Restore:** find the backup in `~/ssot/compile/` and copy it back; remove `~/ssot/compile/MEMORY.candidate.md`.

### 4. Inventory existing sessions (core)

1. `python3 ~/ssot/tools/scan_sessions.py > /tmp/ssmap-scan.tsv`
2. Cluster per `docs/SSMAP.md` §3 → draft `~/ssot/sessions/registry.md` + `~/ssot/lines/<line>.md`
3. Show the user an overview (how many lines / sessions per line / uncertain ones) — **stop and confirm** → finalize.

### 5. Rehearse two loops

Simulate "start a new task on line X" (the three opening questions) and a session close (one line in the registry). Paste the results to the user.

### 6. (Optional) Thin-shell compile

```bash
python3 ~/ssot/tools/sp_compile.py --mem --deploy --target ~/.claude/CLAUDE.md
```
Default target is Qoder's `MEMORY.md`; `--target` (or `SSOT_MEM_TARGET`) covers Claude Code (`~/.claude/CLAUDE.md`), opencode (`AGENTS.md`) and any other entry file.

### 7. (Optional) Semantic layer

Follow `docs/SEMANTIC.md`: fetch the local embedding model → start the service → build the index.

### 8. (Optional) Read-side hooks + 6h steward

```bash
bash scripts/install-hooks.sh            # SessionStart / UserPromptSubmit / Stop drafts
bash scripts/install-steward.sh          # every 6h: incremental index + self-check + draft counts
```
Use `--dry` first; for Claude pass `--settings ~/.claude/settings.json`; uninstall with `--uninstall`.

### 9. (Optional) Pi / opencode extension

Pi has no shell hook; use the global extension (boot injection + recall-triggered search):

```bash
bash scripts/install-pi-extension.sh --dry
bash scripts/install-pi-extension.sh     # → ~/.pi/agent/extensions/ssot-boot.ts
```

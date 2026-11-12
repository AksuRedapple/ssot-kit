# Case study: Agent organization and state governance

> Public asset ID: `agent-organization-governance`
> Narrative series: [可换届的组织](https://ouya15.cn/insights/series/org-governance.html)

## The problem

Long-running coding agents fail organizationally before they fail technically:

- one session accumulates the role, task board, evidence archive, user preferences, and execution history;
- context compaction preserves activity but can lose rejected paths and authorization boundaries;
- role names remain stable while the sessions carrying them keep changing;
- an `idle` process is mistaken for a task that is still progressing;
- a warm prompt cache makes an obsolete session feel current;
- multiple agents share files, HEAD, worktrees, devices, and release authority without an explicit owner.

The project treats these as state-lifetime problems, not prompt-length problems.

## Design position

The central rule is:

> **Organizations can persist; members must rotate. State must live in a layer matched to its lifetime.**

Four boundaries follow from that rule:

| Layer | Correct home | Wrong home |
|---|---|---|
| institutional authority | versioned role contract | chat transcript |
| current term / member | machine-readable term map | role document |
| tasks and waits | task board + wake keys | an idle session |
| evidence | immutable logs and artifacts | generated summary |

SSOT Kit implements the reusable parts of this model: canonical Markdown knowledge, bounded compiled entry files, resumable session records, one-way promotion, task-aware dispatch, handoff, and local retrieval. Personal knowledge and real transcripts remain outside the public repository.

## Narrative path

The public field notes follow the evolution from a single session to an organization:

1. [735 · Session rebirth](https://ouya15.cn/insights/series/735-rebirth.html) — a session has a lifetime; the transfer artifact must preserve rejected paths.
2. [736 · Cabinet terms](https://ouya15.cn/insights/series/736-cabinet-term.html) — roles can persist, but the sessions carrying them cannot be lifetime appointments.
3. [737 · State residency](https://ouya15.cn/insights/series/737-state-residency.html) — SSOT, project memory, task state, evidence, and runtime state need separate homes.
4. [738 · Wait without a session](https://ouya15.cn/insights/series/738-wait-without-session.html) — waiting belongs to a task and is resumed by an event.
5. [739 · Two subagent lifetimes](https://ouya15.cn/insights/series/739-two-subagent-lifetimes.html) — a UI card does not prove which control plane owns the child.
6. [740 · Reversible intervention](https://ouya15.cn/insights/series/740-account-slot-control-plane.html) — emergency switching must be observable, reversible, and independent of model aliases.

## What the repository demonstrates

- a local-first implementation rather than a memory SaaS landing page;
- explicit schemas, migration paths, and failure detection;
- packaged regression tests plus isolated install/upgrade preflight;
- release metadata, tag consistency, public-surface auditing, and secret scanning in CI;
- a documented boundary between reusable framework code and private content;
- a system whose concepts came from incidents, not from a feature checklist.

## What it does not claim

- It is not a general-purpose autonomous-agent runtime.
- It does not eliminate context limits or model errors.
- The organization model has been exercised primarily in one long-running personal engineering workflow; that is useful evidence, not proof of universal scale.
- Interfaces are still `0.x` and may evolve.
- The semantic layer requires a local embedding service and is optional.

## Validation

```bash
bash scripts/release-check.sh
bash scripts/public-audit.sh
bash tools/tests/run_all.sh
bash scripts/preflight.sh --quiet
```

The public repository contains code, templates, and documentation only. Transcripts, private knowledge, embeddings, indexes, credentials, and machine-specific configuration stay local.

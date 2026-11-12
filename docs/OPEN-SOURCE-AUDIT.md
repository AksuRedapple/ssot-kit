# Open-source readiness audit

Date: 2026-11-12 (finalized for v0.13.1)

## Decision

**GO**, with a clean public Git history.

The code is suitable for a public portfolio and open-source release. The private development history is not published because older commits contain personal absolute paths and an owner name that are no longer needed publicly.

## Checks

| Area | Result |
|---|---|
| License | MIT, complete |
| Tracked payload | ~110 source/doc files, under 2 MiB; no vendored dependencies |
| Current-tree secrets | No private keys, API tokens, passwords, or token-shaped assignments detected |
| Current-tree machine data | No personal absolute paths, private IPs, indexes, embeddings, transcripts, or database files |
| Git history | 4 historical commits contained personal paths/name; public release therefore uses a fresh history |
| Install safety | setup/update/preflight run without network by default |
| Tests | packaged tests and isolated preflight pass locally |
| CI | GitHub Actions on macOS, plus tag/version consistency |
| Changelog | Keep a Changelog format with release dates and `[Unreleased]` |
| Security policy | private vulnerability reporting documented |
| Automated public-surface gate | CI rejects token shapes, personal absolute paths, private IPv4s, and broken relative Markdown links |

## Known limitations

- macOS is the primary tested platform; Linux support exists but has less coverage.
- The optional semantic layer requires a local embedding service.
- Several protocol examples retain legacy harness names and Chinese documentation.
- Public interfaces are still `0.x` and may evolve.

## Publication boundary

The public repository must never include:

- session transcripts or personal knowledge;
- semantic indexes or embeddings;
- credentials, keys, or machine-specific configuration;
- private endpoints, private IPs, or personal absolute paths.

## Release procedure

1. Run release metadata, public-surface audit, shell/Python syntax, packaged tests, and isolated preflight.
2. Create a clean-history public tree from the current release commit.
3. Push `main` to the public repository.
4. Confirm GitHub Actions succeeds.
5. Tag `v<VERSION>` only after CI is green.

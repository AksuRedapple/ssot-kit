# Governance

SSOT Kit is a maintainer-led open-source project.

## Decision model

- The maintainer sets roadmap, release timing, and compatibility policy.
- Issues and pull requests are welcome, but acceptance requires reproducibility, tests where applicable, and no content-layer data.
- Security-sensitive changes may be reviewed privately before merge.

## Compatibility

- Versions follow semantic versioning.
- `0.x` releases may change interfaces; breaking changes are explicit in `CHANGELOG.md`.
- Migration paths belong in `UPGRADE.md` and must be exercised by `scripts/preflight.sh`.

## Content boundary

The public repository contains code, templates, and documentation only. Personal knowledge, transcripts, indexes, credentials, and generated private artifacts are out of scope and must not be committed.

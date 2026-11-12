# Contributing

This repository is the distributable reference implementation of SSOT. Changes are developed against the author's upstream `~/ssot` instance, then synchronized here through the whitelist in `tools/kit_manifest.json`.

## Change flow

1. Create a branch and make the upstream change first.
2. Add or update a packaged test under `tools/tests/`.
3. Add the change to `CHANGELOG.md` under `[Unreleased]`.
4. Run:

   ```bash
   bash scripts/release-check.sh
   bash tools/tests/run_all.sh
   bash scripts/preflight.sh --quiet
   ```

5. Open a pull request using the repository template.

## Release flow

- `VERSION` is the released semantic version.
- At release time, move `[Unreleased]` items into `## [x.y.z] - YYYY-MM-DD`.
- Keep the newest released section first.
- `release-check.sh` and GitHub Actions require `VERSION`, the newest CHANGELOG heading, and `CAPABILITIES.md` to agree.
- A tag must be named `v<VERSION>`.

## Publication boundary

Only files listed by the upstream `kit_manifest.json` are synchronized into `tools/`. Never publish `evidence/`, indexes, local knowledge content, credentials, personal paths, or machine-specific configuration.

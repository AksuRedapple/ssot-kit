# Contributing

SSOT Kit is a local-first reference implementation. Contributions should be
reproducible from a fresh clone and must not depend on the maintainer's local
knowledge instance.

## Development

Requirements: Python 3.10+, Git, Bash, and NumPy.

1. Fork the repository and create a focused branch.
2. Add or update a packaged test under `tools/tests/`.
3. Record user-visible changes in `CHANGELOG.md` under `[Unreleased]`.
4. Run the full local gate:

   ```bash
   bash scripts/release-check.sh
   bash scripts/public-audit.sh
   bash tools/tests/run_all.sh
   bash scripts/preflight.sh --quiet
   ```

5. Open a pull request using the repository template and include the observed
   commands and results.

## Release flow

- `VERSION` is the released semantic version.
- At release time, move `[Unreleased]` items into `## [x.y.z] - YYYY-MM-DD`.
- Keep the newest released section first.
- `release-check.sh` and GitHub Actions require `VERSION`, the newest CHANGELOG heading, and `CAPABILITIES.md` to agree.
- A tag must be named `v<VERSION>`.

## Publication boundary

The repository contains framework code, templates, and documentation only.
Never commit:

- session transcripts, personal knowledge, or organization-internal material;
- semantic indexes, embeddings, databases, or generated private artifacts;
- credentials, private endpoints, personal absolute paths, or machine-specific
  configuration.

`scripts/public-audit.sh`, GitHub secret scanning, and push protection are the
automated backstops. A green scan does not replace human review of the diff.

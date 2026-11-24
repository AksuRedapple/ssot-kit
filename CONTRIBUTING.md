# Contributing

SSOT Kit is a local-first reference implementation. Contributions should be
reproducible from a fresh clone and must not depend on the maintainer's local
knowledge instance.

## Development

Requirements: Python 3.10+, Git, Bash, and NumPy.

1. Fork the repository and create a focused branch.
2. Add or update a packaged test under `tools/tests/`.
3. Record user-visible changes in `CHANGELOG.md` under `[Unreleased]`.
4. Run the gate that matches the change class (see
   [docs/MAINTENANCE.md](docs/MAINTENANCE.md)):

   ```bash
   # A 文档/说明：静态闸即可；发布前再跑一次 preflight
   bash scripts/release-check.sh
   bash scripts/public-audit.sh
   bash tools/tests/shell_strict_test.sh

   # B 工具/测试/模板/技能：加测试与影子安装
   bash tools/tests/run_all.sh tools/tests
   bash scripts/preflight.sh --quiet
   ```

   Do not run the full suite/nightly for a docs-only change; do not rerun
   `preflight` after every edit.

5. Open a pull request using the repository template and include the observed
   commands and results.

## Release flow

> 变更分级、闸与停止规则见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。

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

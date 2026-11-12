# Security Policy

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting / security advisory** for this repository.
Do not open a public issue containing credentials, private paths, transcript content, or exploit details.

## Scope

Security-sensitive areas include:

- secret or personal-content leakage through tracked files or generated drafts;
- shell command injection in install, index, conversion, or hook scripts;
- path traversal or unsafe file replacement;
- cross-session or cross-user data exposure;
- unsafe webhook, MCP, or local-service defaults;
- cache or index behavior that returns content from another session.

## Design boundary

SSOT Kit is a local-first framework. The repository should contain framework code and templates only:

- no personal knowledge or session content;
- no embeddings, semantic indexes, or generated snapshots;
- no credentials, tokens, private keys, or machine-specific secrets;
- no private endpoints or personal absolute paths.

Supported security fixes are applied to the latest `0.13.x` line until the next minor release.

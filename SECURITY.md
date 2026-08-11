# Security Policy

Sentinel handles network data, downloads files, and can modify the software
you point it at — security matters here. This document explains what is
supported and how to report a vulnerability.

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| main    | ✅ actively developed |
| < 0.1.0 | ❌ not released     |

Only the latest release (and `main`) receive security fixes. Once a release
exists, older releases are not patched.

## Reporting a vulnerability

**Do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://docs.github.com/code-security/security-advisories/working-with-security-advisories/configuring-private-vulnerability-reporting-for-a-repository)
for this repository, or email the maintainer directly (see the repository
profile). Reports are acknowledged within 48 hours and handled privately.

Please include:

- the affected version / commit
- a minimal reproduction (commands, config, expected vs. actual behavior)
- impact assessment (what an attacker could do)
- a proposed fix, if you have one

### What we care about most

- **Supply chain integrity** — anything that could let a monitored "official"
  source serve malicious artifacts (checksum bypass, unverified downloads,
  path traversal in install paths or asset names, marker-file forgery).
- **Secret handling** — tokens, header values, config and database contents
  that could leak credentials (masking gaps, logging, `sentinel show`).
- **Network abuse** — the HTTP layer touching unexpected schemes or hosts,
  SSRF-like behavior through user-supplied URLs, redirect handling.
- **Data safety** — the SQLite store (corruption, injection) and anything in
  the upgrade path that could destroy or overwrite files outside the
  configured install path.

## Security-relevant behavior (maintained on purpose)

- Monitoring is passive; updating is explicit (`--dry-run` by default, then
  confirmation or `--yes`).
- Downloads without a verifiable checksum are blocked unless
  `--allow-unverified` is passed explicitly.
- Only `http`/`https` URLs are ever opened by the transport layer.
- Secrets are never stored in the database and are masked in output.
- Every applied update is recorded in the `updates` audit table.

## Security tooling in CI

Every pull request runs: `ruff` (incl. security rules), `bandit` static
analysis, `pip-audit` for dependency vulnerabilities, and the full test
suite on Python 3.11–3.14. Dependabot keeps the (deliberately tiny) supply
chain up to date, and Actions are pinned to commit SHAs.

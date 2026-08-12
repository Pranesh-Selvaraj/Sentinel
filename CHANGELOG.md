# Changelog

All notable changes to Sentinel are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-08-12

### Added

- **PyPI package monitor** — `sentinel add pypi requests` watches the latest
  release of any Python package via the official PyPI JSON API, with
  interactive and non-interactive add, change detection (including rollback
  warnings), and full `check`/`status`/`history`/`show` support.
- **npm package monitor** — `sentinel add npm express` watches the latest
  release of any npm package via the official npm registry
  (`dist-tags.latest`), with the same capabilities as the PyPI monitor.
- **`sentinel uptime` command** — uptime statistics computed from the
  per-attempt checks log: per-source and overall percentages with
  check/failure counts, over a configurable window (`--days`, `0` = all
  history), with `--json` output.
- **`retention_days` configuration** — `[sentinel] retention_days` (default
  90, `0` keeps everything) prunes the per-attempt `checks` log on startup so
  the database cannot grow without bound. History and the `updates` audit
  trail are never pruned.
- **CI packaging job** — a new `package` job in CI builds the wheel, installs
  it into a clean virtualenv, and smoke-tests the installed CLI so packaging
  regressions are caught on every push/PR.

### Fixed

- **Critical: broken installed distribution** — `sentinel.updaters` was
  missing from the built wheel, so every command crashed with
  `ModuleNotFoundError` after `pip install .` (CI only ever used editable
  installs and never caught it). Packaging now uses
  `[tool.setuptools.packages.find]`, and the new CI `package` job guards it.
- **429 responses were never retried** — transient rate limits failed checks
  immediately. The transport now retries 429 like other transient statuses
  and honors a server-sent `Retry-After` header (seconds or HTTP-date,
  capped at 60 s). Exhausted GitHub rate limits (403 with
  `X-RateLimit-Remaining: 0`) and other 4xx errors are still never retried.
- **Interactive add could not enable upgrades** — the interactive
  "Software/release (GitHub releases)" flow now asks for an optional install
  path, making interactively-added sources updatable via `sentinel upgrade`
  (previously only the non-interactive `--install-path` flag worked).
- **Test double fidelity** — `FakeTransport.get_json` now raises
  `FetchInvalidJSON` on non-JSON bodies exactly like the real transport, so
  tests can no longer disagree with production behavior.

## [0.1.0] — 2026-08-11

Initial release: **Sentinel — a universal source & software change monitor.**

### Added

- **Source monitoring**
  - GitHub repositories: releases, tags, or commits (`sentinel add github
    owner/repo --monitor release|tags|commits`), with repository existence
    verification at add time and optional `GITHUB_TOKEN` authentication.
  - Websites: HTTP status, content fingerprint (SHA-256), page title
    (`sentinel add http URL`).
  - API endpoints: HTTP status plus JSON body or extracted JSON field via
    `--jpath` (supports `$.a.b`, `$.a[0].b`, bare `a.b`), with per-request
    headers that may reference environment variables (`${API_KEY}`).
  - Interactive and non-interactive `sentinel add` flows.
- **Change detection & history**
  - Append-only SQLite state store (`sources`, `snapshots`, `changes`,
    `checks`, `updates` tables) with cascading deletes and persistence
    across reopen.
  - Reusable diff strategies: version transitions (loose semver parsing,
    prerelease-aware, rollback detection), HTTP status, JSON field, content
    hash, scalar values with numeric deltas, and availability
    online/offline transitions with recovery detection.
  - `sentinel history` and `sentinel show` (config, masked secrets, raw
    preview, recent changes).
- **Commands & scripting**
  - `sentinel list`, `sentinel status`, `sentinel check`, `sentinel remove`,
    `sentinel watch`, `sentinel config`.
  - Exit codes for scripting: `0` no changes, `1` changes detected, `2`
    failures (`--exit-zero` to opt out); `--json` output on every
    data-producing command.
  - Watch mode with configurable interval and clean Ctrl-C exit.
- **`sentinel upgrade` — official-source updater system**
  - GitHub release updater: dry-run planning (never mutates), asset
    selection via fnmatch patterns, checksum discovery and verification
    (sibling `.sha256`/`.sha512` files, `SHA256SUMS`, `checksums.txt`, …),
    blocked unverified downloads unless `--allow-unverified`, explicit
    confirmation (`--yes` for scripting), version marker file, and a full
    `updates` audit trail.
  - `sentinel update` — checks PyPI for a newer Sentinel release (best
    effort, honest about unverifiable provenance).
- **Robustness & security**
  - Single HTTP transport with timeouts, retries with jittered backoff
    (5xx + network errors), and typed errors (timeout, connection, HTTP,
    rate-limited, invalid JSON).
  - One failing source never crashes a check run; availability transitions
    are recorded.
  - Only `http`/`https` URLs are ever opened; other schemes are rejected.
  - Secrets never stored in the database and masked in output
    (`mask_secrets`); header values prefer `${ENV_VAR}` references.
  - Platform-aware config directory (`~/.sentinel/`, macOS Application
    Support, `%APPDATA%`), `SENTINEL_HOME` override, `config.toml`
    (`check_interval`, `timeout`, `retries`, `user_agent`, `[github] token`).
- **Engineering**
  - Zero runtime dependencies (Python 3.11+ standard library only).
  - 157 tests covering version comparison, all diff strategies, JSON-path
    resolution, configuration, SQLite persistence, all monitors (mocked
    HTTP), transport retries, CLI behavior and exit codes, upgrade
    planning/verification/application, and the watch scheduler.
  - CI pipeline: tests on Python 3.11–3.14, ruff lint + format, bandit and
    pip-audit security checks.
  - MIT license, contributing and security guidelines, branch-protected
    `main` with PR-only workflow.

[0.2.0]: https://github.com/Pranesh-Selvaraj/Sentinel/releases/tag/v0.2.0
[0.1.0]: https://github.com/Pranesh-Selvaraj/Sentinel/releases/tag/v0.1.0

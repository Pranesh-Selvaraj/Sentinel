# Sentinel

**A universal source & software change monitor for developers.**

> Add it once. Sentinel watches it. Know when it changes.

Sentinel is a lightweight CLI tool that monitors websites, APIs, and GitHub
repositories for changes. It remembers the previous state of everything it
watches, explains exactly what changed (not just *that* it changed), and is
architected to one day update software from its verified official sources —
safely.

Monitoring is **passive**. Updating is **explicit and potentially destructive**.
Those capabilities are kept strictly separate.

---

## Why it exists

Developers care about a lot of things that change:

- the latest release of the tools they use (`microsoft/vscode`, `python/cpython`)
- whether a website or API they depend on is up
- version fields in JSON endpoints (`$.version`)
- commits landing on important repositories

Checking all of these by hand is tedious and forgetful. Sentinel turns "I
should check that" into a repeatable, inspectable, scriptable routine — and
keeps a durable history so you can see *when* something changed, not just that
it did.

---

## Installation

Requires **Python 3.11+** and no third-party dependencies.

```bash
git clone https://github.com/Pranesh-Selvaraj/Sentinel.git
cd sentinel
pip install .
```

Or run it straight from the source tree without installing:

```bash
python3 -m sentinel --help
```

Verify:

```bash
sentinel --version
```

---

## Quick start

```bash
sentinel add github microsoft/vscode --monitor release
sentinel add github python/cpython --monitor release
sentinel add http https://example.com
sentinel add api https://api.github.com/repos/microsoft/vscode --jpath '$.stargazers_count'

sentinel list
sentinel check
sentinel status
```

Realistic output:

```
$ sentinel check
Sentinel

Checking 4 sources...

✓ microsoft/vscode
  1.132.0 — no change

✓ python/cpython
  — no releases yet — no change

✓ Example.com
  HTTP 200 — no change

✓ VS Code Stars
  188546 — no change

No changes detected.
```

When something *does* change:

```
⚠ VS Code
  1.102.0 → 1.103.0
  New release detected

✗ example.com
  HTTP 200 → HTTP 404

⚠ My Product
  $.version:
  1.4.2 → 1.5.0

3 changes detected.
```

---

## CLI reference

```
sentinel add        Add a source to monitor (interactive, or: add github/http/api …)
sentinel remove     Remove a source
sentinel list       List all sources
sentinel check      Check all sources, report and store changes
sentinel status     Overview: sources, current values, health, updates
sentinel show       Full detail of one source (config, raw preview, recent changes)
sentinel history    A source's observation history
sentinel watch      Check repeatedly and print changes as they happen
sentinel update     Check for updates to Sentinel itself
sentinel upgrade    Check monitored software for available updates (dry-run safe)
sentinel config     Show configuration and paths
```

### Adding sources

Interactive (pick a type, answer a few questions):

```bash
sentinel add
```

```
What do you want to monitor?

❯ GitHub repository
  Website
  API endpoint
  Software/release (GitHub releases)
```

Non-interactive:

```bash
sentinel add github microsoft/vscode --monitor release     # release | tags | commits
sentinel add github microsoft/vscode --monitor commits --name "VS Code commits"
sentinel add github jqlang/jq --install-path ~/tools/jq \
    --asset 'jq-linux-amd64'                              # enables `sentinel upgrade`
sentinel add http https://example.com --name "My Website"
sentinel add api https://api.example.com/version --jpath '$.version'
sentinel add api https://api.example.com/x --header 'X-Api-Key=${API_KEY}'
```

GitHub repositories are verified to exist on add (`--skip-verify` to skip).
`--install-path` marks a repo as *updatable*: `sentinel upgrade` will then
download verified release assets into `<install-path>/<version>/`.
`--asset` selects which release assets to download (fnmatch pattern,
repeatable; default: the largest non-checksum asset).

### Checking

```bash
sentinel check                 # all sources
sentinel check VS Code         # by id, name, or unique name prefix
sentinel check --exit-zero     # always exit 0
sentinel check --json          # machine-readable
```

Exit codes: `0` = no changes, `1` = changes detected, `2` = one or more
sources failed to check. Use `--exit-zero` in scripts that don't care.

### Watching

```bash
sentinel watch
sentinel watch --interval 10m
```

```
Sentinel watching 5 sources... (interval: 10m)

[10:00] ✓ No changes
[10:10] ✓ No changes
[10:20] ⚠ 2 changes detected

VS Code
  1.102.0 → 1.103.0
  New release detected
```

Ctrl-C stops cleanly. The default interval comes from `config.toml`.

### History & details

```bash
sentinel history VS Code
sentinel history VS Code --limit 30
sentinel show VS Code
```

```
VS Code History

Aug 10  1.103.0
Aug 03  1.102.0
Jul 27  1.101.2
```

### update vs upgrade — and safety

`sentinel update` checks whether a newer **Sentinel** itself exists.
`sentinel upgrade` updates the **software Sentinel manages**.

Make a GitHub release source updatable by giving it an install path and
(optionally) an asset pattern at add time:

```bash
sentinel add github jqlang/jq --monitor release \
    --install-path ~/tools/jq \
    --asset 'jq-linux-amd64'
```

Then check what would happen, and apply it:

```bash
sentinel upgrade --dry-run          # plan only, changes nothing
sentinel upgrade                    # confirm, then download + verify
sentinel upgrade --yes              # skip confirmation (scripting)
sentinel upgrade jq                 # only the selected sources
sentinel upgrade --allow-unverified # allow downloads without checksums
sentinel upgrade --json             # machine-readable
```

```
$ sentinel upgrade

Checking official sources...

jqlang/jq
  Installed: not downloaded
  Latest:    jq-1.8.2
  Source:    https://github.com/jqlang/jq/releases/tag/jq-1.8.2
  Asset:     jq-linux-amd64 (2.2 MB) → ~/tools/jq/jq-1.8.2/
  Verify:    checksum verified (sha256/sha512)

1 update available.

Proceed? [y/N]
```

How it works:

- the latest release is read from the **official GitHub release**;
- the selected asset(s) are downloaded into `<install-path>/<version>/`;
- checksums are verified when the release ships them (`<asset>.sha256`,
  `SHA256SUMS`, `sha256sum.txt`, `checksums.txt`, …);
- downloads without any checksum are **blocked** unless you pass
  `--allow-unverified`;
- nothing is ever executed — this updater downloads and verifies artifacts;
- every attempt is recorded in the `updates` audit table (see
  `sentinel show` / the SQLite database);
- a `.sentinel-version` marker records what is installed, so the next run
  reports `already up to date`.

Sources that are not updatable are reported honestly — websites and APIs are
monitoring-only, and GitHub sources without an `--install-path` tell you how
to enable updates. Exit code: `0` when everything applied, `1` when any
update failed.

---

## Supported sources

| Type    | Watches                     | Updatable?                              | Example config                    |
| ------- | --------------------------- | --------------------------------------- | --------------------------------- |
| `github`| releases, tags, or commits  | releases, with `install_path` + assets  | `{"repo": "microsoft/vscode", "monitor": "release"}` |
| `http`  | HTTP status + content hash (+ page title) | monitoring only            | `{"url": "https://example.com"}` |
| `api`   | HTTP status + JSON body / extracted JSON field | monitoring only       | `{"url": "…", "jpath": "$.version"}` |

`jpath` supports `$.a.b`, `$.a[0].b`, and bare `a.b`. If the path is missing
from the response, the value is tracked as absent — and its appearance or
disappearance is reported.

### Authentication

- **GitHub**: set `GITHUB_TOKEN` (or `[github] token` in `config.toml`).
  Tokens raise rate limits and are never stored in the database or printed.
- **APIs**: extra headers via `--header 'X-Api-Key=${API_KEY}'` — values may
  reference environment variables, so secrets never need to live in the
  database. Header values are masked in `sentinel show` output.

---

## Configuration

```
~/.sentinel/
├── config.toml
└── sentinel.db
```

Platform-aware defaults:

| Platform | Config directory                        |
| -------- | --------------------------------------- |
| Linux    | `~/.sentinel/`                          |
| macOS    | `~/Library/Application Support/Sentinel/` |
| Windows  | `%APPDATA%\Sentinel\`                   |

`SENTINEL_HOME` overrides the directory anywhere. `sentinel config --path`
prints it for scripts.

```toml
# config.toml
[sentinel]
check_interval = "1h"   # default interval for `sentinel watch`
timeout = 30            # seconds per request
retries = 3             # retries on network errors / 5xx

[http]
user_agent = "sentinel/0.1.0"

# [github]
# token = "ghp_..."     # prefer the GITHUB_TOKEN environment variable
```

State lives in SQLite: `sources`, `snapshots` (append-only observations),
`changes` (detected changes with explanations), `checks` (per-attempt health
log), and `updates` (future upgrade audit trail).

---

## Architecture

```
CLI (argparse)
 │
 ├── Commands ──────── thin dispatch, no business logic
 │
 ├── SentinelApp ───── application services (add/check/status/history/watch)
 │     ├── Source Registry  (monitors/__init__.py)
 │     ├── Monitors         (monitors/: base, github, http, api)
 │     ├── State Store      (db.py — SQLite)
 │     ├── Change Detector  (diffing.py — reusable comparison strategies)
 │     ├── Version System   (versions.py — loose semver comparison)
 │     ├── Update System    (update.py — updater/verifier interfaces, planning)
 │     └── Watch Scheduler  (watcher.py)
 │
 ├── Transport        (httpclient.py — timeouts, retries, typed errors)
 │
 └── Display          (display.py + term.py — human/JSON rendering)
```

Key interfaces (see `sentinel/monitors/base.py`, `sentinel/updaters/base.py`):

- **Monitor** — observes a source type and diffs two observations into
  `Change`s. Adding a new source type = implement one class, register it.
- **Updater** — plans (`--dry-run`-safe) and applies updates for a source
  kind. `GitHubReleaseUpdater` downloads release artifacts from the official
  GitHub release into the source's `install_path`, verifying checksums when
  the release ships them. Adding a new updater = implement one class, register it.
- **VersionProvider / Verifier** — read the latest version from an official
  source; verify downloaded artifacts. A `Notifier` interface is planned.

Rules that keep Sentinel honest:

- one failing source never crashes a check run (retries, per-source errors,
  availability transitions recorded)
- secrets are never printed (`mask_secrets` in `show`, `${ENV}` references)
- upgrade planning never mutates anything (`--dry-run` by default; apply
  requires confirmation or `--yes`)
- downloads without a verified checksum are blocked unless
  `--allow-unverified` is passed explicitly
- every applied update lands in the `updates` audit table

---

## Development

```bash
git clone https://github.com/Pranesh-Selvaraj/Sentinel.git
cd sentinel
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Testing

Tests use only the standard library (`unittest`) and a fake HTTP transport —
**no live network**:

```bash
python3 -m unittest discover -s tests -v
```

Covered: version comparison, all diff strategies, JSON-path resolution,
configuration loading, SQLite persistence (incl. across reopen), GitHub
releases/tags/commits fetching and diffing (mocked HTTP), HTTP status/content
changes, API JSON extraction and header env-expansion, the full
add → check → change → history flow, failure isolation and recovery,
upgrade planning/checksum verification/download application and the audit
trail, CLI command behavior and exit codes, and the watch scheduler.

---

## Roadmap

- [x] GitHub releases / tags / commits monitoring
- [x] HTTP status + content-change monitoring
- [x] API monitoring with JSON field extraction
- [x] SQLite state store, history, change explanations
- [x] Watch mode, JSON output, exit codes for scripting
- [ ] New source types: npm, PyPI, Docker Hub, RSS, product prices, GitLab,
      certificates/domains
- [ ] Notifications (desktop, webhook, email)
- [x] Official-source updaters for supported software (`sentinel upgrade`)
      with checksum verification, dry-run, confirmation, and audit trail
      (GitHub releases; npm/PyPI/Docker/… updaters next)
- [ ] Signature verification (cosign/minisign) and provenance attestations
- [ ] Self-update verification for published distributions
- [ ] Uptime statistics from the `checks` log

---

## License

MIT

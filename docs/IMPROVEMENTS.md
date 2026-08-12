# Sentinel — Improvements & Feature Suggestions

Prioritized, concrete ideas for where Sentinel can go next. Each entry
states the problem it solves and a suggested shape, so any of them can be
picked up as a `feat/…` branch without further design work. The tracking
issue links (where present) keep the conversation in GitHub.

Priorities:

- **P0** — high value, fits the existing architecture
- **P1** — valuable, moderate design work
- **P2** — nice to have / exploratory

---

## P0 — Do these next

### Notifications (webhook / desktop / email) — *README roadmap*

*Problem:* `sentinel check` in a cron job only tells you something
changed if you read its output.

*Shape:* a `Notifier` interface (already anticipated in
`sentinel/updaters/base.py` docs) with two built-ins first:

- **webhook**: POST the change payload (same shape as `check --json`) to
  a configured URL — Slack/Discord/Teams/Generic. Header values support
  `${ENV_VAR}`, like API headers.
- **command hook**: `[notify] command = "…"` — Sentinel runs the command
  with the JSON payload on stdin when changes are detected. Safe: never
  pass secrets, never pass raw page content.

Config: `[notify] on_change = "webhook" / "command"`, per-notifier
settings, `notify = false` default. Gate on the same change payload used
by `check --json` so behavior is testable with the fake transport.

### npm / PyPI / Docker updaters — *README roadmap*

*Problem:* `sentinel upgrade` currently only handles GitHub releases;
packages from registries can be watched but not installed/verified.

*Shape:* extend `Updater` implementations:

- **PyPI**: download the sdist (or the wheel matching the current
  platform — `pip download --no-deps` semantics), verify against the
  SHA256 published in the PyPI JSON API.
- **npm**: download the tarball from `registry.npmjs.org` (`dist.tarball`),
  verify its `integrity` field (SRI format).
- **Docker**: out of scope for artifact download (images are layers, not
  files) — instead a `docker pull --platform` wrapper documented as
  optional and off by default.

All must follow the safety rules: dry-run planning, checksum/SRI
verification, confirmation, audit trail.

### `sentinel status --local` — issue S-6

*Problem:* `status` hits the network via `plan_all()`; slow and
offline-unfriendly for an overview command.

*Shape:* `--local` renders only from the database (no `plan_all`); the
updates section shows "run `sentinel upgrade` to check" instead. Consider
a `plans` cache table refreshed by `upgrade`/`check` later.

### Concurrent checks — *scalability*

*Problem:* with many sources, `sentinel check` fetches sequentially; one
slow source delays everything (retries can take minutes).

*Shape:* a small `ThreadPoolExecutor` in `SentinelApp.check()` (a few
workers, configurable `[sentinel] max_workers`), keeping per-source
isolation guarantees. Results stay ordered by source id for stable
output. Tests use the fake transport, so concurrency is deterministic.

---

## P1 — Strong candidates

### More source types — *README roadmap*

Each is one `Monitor` class + registration + CLI subcommand, exactly like
`feat/pypi-monitor` / `feat/npm-monitor`:

- **Docker Hub**: tags of a repo (`hub.docker.com/v2/repositories/…/tags`),
  diff the latest semver-ish tag.
- **RSS/Atom**: parse with the stdlib `xml.etree`, diff latest entry
  title/date/guid. Covers blogs, release feeds, security advisories.
- **GitLab**: releases/tags via the GitLab API (mirror the GitHub
  monitor; `GITLAB_TOKEN` for private repos).
- **Certificates/domains**: TLS certificate expiry + DNS records for a
  domain — "your cert expires in 12 days" as a monitored value. Uses
  `ssl` + `socket` (still stdlib; goes through `Transport`-adjacent code
  with timeouts).
- **Product prices**: reuse `ChangeDetector.scalar` (already written and
  tested) with a CSS/XPath-lite selector.

### ETag / Last-Modified support for `http` monitors

*Problem:* the HTTP monitor re-downloads the full body every check, even
when nothing changed.

*Shape:* store the response `ETag`/`Last-Modified` in the observation
state and send conditional `If-None-Match`/`If-Modified-Since` headers;
treat 304 as "no change" without a body fetch. Big bandwidth win for
large pages, and a nice demonstration of the state-diff architecture.

### `sentinel export` / `sentinel import`

*Problem:* sources and history live in a local SQLite file; there is no
way to back up config or migrate machines.

*Shape:* `export --json` (sources + snapshots + changes) and `import`
(restore; refuse to overwrite existing sources without `--yes`). Uses
`mask_secrets` on output unless `--no-mask` for true backups.

### Alert deduplication & throttling

*Problem:* a flapping source (availability up/down) fills `changes` and
would spam notifications.

*Shape:* skip recording a change identical to the latest stored one for
the same source (`kind` + `previous` + `current`), optionally with a
cooldown per source (`[sentinel] change_cooldown = "15m"`). Cheap query,
big quality win.

### Per-source check intervals in watch mode

*Problem:* watch polls everything at one interval; APIs that change
hourly and pages that change weekly don't need the same cadence.

*Shape:* per-source `check_interval` in config + a priority queue in
`Scheduler` instead of a single tick loop.

---

## P2 — Further out

- **Signature verification** (cosign/minisign) and provenance
  attestations for downloaded artifacts — the "trust" layer on top of
  checksum verification. *README roadmap.*
- **Self-update verification** for published distributions — verify
  sdist/wheel signatures or at least pinned checksums before telling the
  user to `pip install --upgrade`. *README roadmap.*
- **`sentinel doctor`** — self-diagnostics: config validity, database
  integrity (`PRAGMA integrity_check`), schema version vs `SCHEMA_VERSION`,
  connectivity probes to registered sources, token presence (never the
  value), directory permissions.
- **Change severity scoring** — weigh a change by source kind and delta
  (e.g. a GitHub release that *rolls back* matters more than a forward
  bump), surfaced in `check` output and notifications.
- **Anomaly detection on scalars** — for price/version monitors, flag
  jumps beyond N standard deviations of the source's own history.
- **Proxy support & custom CAs** — `HTTPS_PROXY`/`HTTP_PROXY` (urllib
  honors these natively once verified) and a `[http] ca_bundle` option.
- **Team sync / multi-machine state** — push snapshots to a shared
  backend so a team sees one history. Big design; start with
  import/export.
- **Web UI** — a small read-only server (`sentinel serve`) rendering
  status/history; the JSON output shapes already exist, so a static
  frontend can consume them without new backend work.
- **Packaging** — Homebrew formula and a Docker image for scheduled
  `check` runs (cron + notifications make this actually useful).
- **Precise scheduler** (issue S-10) — deadline-based ticks instead of
  interval-after-tick.

---

## Quick wins (small, well-scoped)

1. `sentinel watch --json` (stream `check --json`-shaped lines) — makes
   watch scriptable.
2. `sentinel check --json` gains `source_id` and `observed_at` — easier
   to correlate with history.
3. `--max-body` / `--fingerprint` options on `http` sources (some pages
   embed timestamps that would otherwise cause false positives; an
   exclude-regex for volatile regions would help too).
4. `sentinel history --json` includes `raw` previews (currently dropped).
5. `sentinel upgrade --all-assets` — download every pattern-matched
   asset, not just the default largest one, in one go.
6. `sentinel check` exit code 3 when *any* rate limit was hit, so cron
   can distinguish "down" from "throttled".
7. `SENTINEL_CONFIG` env var in addition to `SENTINEL_HOME` for pointing
   at a specific `config.toml`.
8. Retry counters surfaced in `check` output for failed sources
   (`after 2 retries` already exists in error text — show it in the
   `checks` table too).
9. `NO_COLOR`-aware JSON output (already handled) and a `--color=auto`
   flag for scripting.
10. Ship a `sentinel.timer`/systemd unit example in `examples/` so
    `sentinel check` on a schedule is a one-copy-paste setup.

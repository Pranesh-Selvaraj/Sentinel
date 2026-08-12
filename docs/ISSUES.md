# Sentinel Issue Catalog

A living catalog of known issues, bugs, and gaps found during code review
and testing. Each entry records severity, status, and where the fix landed.
Open items are tracked on GitHub (see links) and in
[IMPROVEMENTS.md](IMPROVEMENTS.md) for the feature-shaped ones.

Status legend:

- **fixed** — resolved; the fixing commit/branch is named
- **open** — still outstanding; linked to a GitHub issue
- **by-design** — intentional behavior worth documenting

---

## Fixed

### S-1 (critical, fixed) — installed wheel missing `sentinel.updaters`

`pyproject.toml` listed only `sentinel` and `sentinel.monitors` under
`[tool.setuptools] packages`, so `pip install .` produced a wheel without
`sentinel.updaters/`. Because the CLI imports `sentinel.app` →
`sentinel.update` → `sentinel.updaters` at startup, **every command
crashed with `ModuleNotFoundError`** in an installed distribution. CI
never caught it because it installs with `pip install -e .` (editable).

Fix: `[tool.setuptools.packages.find]` (include `sentinel*`) + a new CI
`package` job that builds the wheel, installs it into a clean venv, and
smoke-tests the installed CLI. Branch `fix/packaging-updaters`, commit
`4544b60`.

### S-2 (medium, fixed) — transient 429 responses were never retried

The transport retried network errors and 5xx, but a 429 (rate limit) —
transient by definition — failed the check immediately, even though the
server may have told us exactly when to retry via `Retry-After`.

Fix: 429 is now retried like other transient statuses; a server-sent
`Retry-After` (seconds or HTTP-date) is honored, capped at 60s. Exhausted
GitHub rate limits (403 + `X-RateLimit-Remaining: 0`) and other 4xx are
still never retried. Branch `fix/retry-429`, commit `8e555da`.

### S-3 (medium, fixed) — `checks` table grew without bound

Every check attempt appends a `checks` row per source — in watch mode
that is every interval, forever. Nothing ever pruned it.

Fix: `[sentinel] retention_days` setting (default 90, `0` keeps
everything); `Database.prune()` runs at startup and removes old per-attempt
rows. History (`snapshots`/`changes`) and the `updates` audit trail are
never pruned. Branch `fix/db-retention`, commit `3c0b1a5`.

### S-4 (medium, fixed) — interactive `add` could not enable upgrades

The interactive flow offered "Software/release (GitHub releases)" but had
no way to set an install path, so sources added interactively could never
be upgraded — only the non-interactive `--install-path` flag worked.

Fix: the release prompt now asks for an optional install path, exactly
equivalent to `--install-path`. Branch `fix/interactive-updatable-add`,
commit `52bd7cd`.

### S-5 (low, fixed) — test double diverged from the real transport

`FakeTransport.get_json` raised a raw `json.JSONDecodeError` on non-JSON
bodies, while the real `Transport.get_json` raises `FetchInvalidJSON`.
Tests could therefore pass against the fake but fail against the real
transport (and vice versa).

Fix: the fake now mirrors the real error contract. Commit `9bb4c04`
(feat/pypi-monitor branch).

---

## Open

### S-6 (medium, open) — `sentinel status` performs network calls

[GitHub issue #3](https://github.com/Pranesh-Selvaraj/Sentinel/issues/3)

`SentinelApp.status()` runs `UpgradeService.plan_all()`, which fetches
the latest release from the network for every updatable source. That
makes `sentinel status` slow and network-dependent — surprising for an
"overview" command that should render from the local database.

Suggested fix: a `--local` flag (database only, no network), or a cached
plan table refreshed only by `sentinel upgrade`/`sentinel check`.

### S-7 (low, open) — digit-only source names are shadowed by ids

[GitHub issue #2](https://github.com/Pranesh-Selvaraj/Sentinel/issues/2)

`resolve()` treats any all-digit `ref` as a source id first, so a source
*named* `"123"` can never be addressed by name (only by id). Edge case;
fix by trying exact-name matches before id matches when a digit-named
source exists.

### S-8 (low, open) — `Observation.fetched_at` is never populated

[GitHub issue #10](https://github.com/Pranesh-Selvaraj/Sentinel/issues/10)

The field exists on the model and is even used (`fetched_at or now` in
`_check_one`), but no monitor ever sets it, so snapshots always carry the
check time rather than the server-reported observation time. Populate it
where the source reports a timestamp (GitHub `published_at`, PyPI/npm
upload times).

### S-9 (low, open) — `sentinel watch` header counts disabled sources

[GitHub issue #4](https://github.com/Pranesh-Selvaraj/Sentinel/issues/4)

The banner says "watching N sources" using `list_sources()` without
`enabled_only=True`, so disabled sources are counted (and `check` inside
watch skips them). Cosmetic, but misleading.

### S-10 (low, open) — scheduler drift in watch mode

[GitHub issue #8](https://github.com/Pranesh-Selvaraj/Sentinel/issues/8)

`Scheduler` uses `threading.Event.wait(interval)` — the tick happens
after the wait, so each cycle drifts by the check's own duration. Fine
for human watching; not fine for precise cron-like polling. Fix:
compute the next deadline and wait `deadline - now` (or move to a
`time.sleep` loop).

---

## By design (documented behavior, not bugs)

- **Monitoring never mutates anything; upgrading is explicit and gated**
  (confirmation / `--yes`, `--dry-run` planning, checksum verification,
  `updates` audit trail). Safety rules in `CONTRIBUTING.md`.
- **One failing source never crashes a check run** — per-source errors,
  availability transitions, retries with backoff.
- **Secrets never stored**: header values may reference `${ENV_VAR}`;
  `mask_secrets()` hides credential-like config in `sentinel show`.
- **Only `http`/`https` URLs are ever opened** by the transport; other
  schemes are rejected up front.
- **`sentinel status` includes update plans** (see S-6 for the cost).
- **Exhausted GitHub rate limits are never retried** (403 +
  `X-RateLimit-Remaining: 0`) — retrying would waste attempts; the error
  tells you when it resets.

---

## How issues are tracked

Fixed items live in this file with their commits. Open items have GitHub
issues (links above where present) so they stay visible and triageable.
New findings should be added here with a severity and either a fixing
commit or a GitHub issue link.

"""Application services.

The CLI is a thin argument parser; all real work happens here. Each method
returns plain data (dataclasses / dicts) so it can be rendered as human text
or JSON without duplication.
"""

from __future__ import annotations

from typing import Self

from sentinel.config import Settings, load_settings
from sentinel.db import Database
from sentinel.diffing import ChangeDetector
from sentinel.errors import FetchError, SentinelError, UsageError
from sentinel.httpclient import Transport
from sentinel.models import CheckResult, Source, UpdatePlan, UpdateResult
from sentinel.monitors import get_monitor
from sentinel.update import SelfUpdateService, UpgradeReport, UpgradeService
from sentinel.updaters import get_updaters
from sentinel.util import utc_now
from sentinel.watcher import Scheduler


class SentinelApp:
    """Orchestrates Sentinel's services. Persistence via SQLite."""

    def __init__(
        self, config_dir=None, settings: Settings | None = None, transport: Transport | None = None
    ) -> None:
        self.settings = settings or load_settings(config_dir)
        self.db = Database(self.settings.db_path)
        self.transport = transport or Transport(
            timeout=self.settings.timeout,
            retries=self.settings.retries,
            user_agent=self.settings.user_agent,
            github_token=self.settings.github_token,
        )

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- source management ------------------------------------------------
    def add(self, kind: str, config: dict, name: str | None = None, verify: bool = True):
        """Register a source. Returns ``(source, warnings)``."""
        monitor = get_monitor(kind)
        source_name = name or monitor.default_name(config)
        warnings: list[str] = []
        if kind == "github" and verify:
            warning = self._verify_github_repo(config.get("repo", ""))
            if warning:
                warnings.append(warning)
        created = utc_now()
        source_id = self.db.add_source(kind, source_name, config, created)
        return self.db.get_source(source_id), warnings

    def _verify_github_repo(self, repo: str) -> str | None:
        """Best-effort existence check on add. Returns a warning string or None."""
        from sentinel.monitors.github import github_headers

        url = f"https://api.github.com/repos/{repo}"
        try:
            data = self.transport.get_json(url, github_headers(self.transport))
            if not isinstance(data, dict) or "full_name" not in data:
                return None  # looks fine
        except FetchError as exc:
            if getattr(exc, "status", None) == 404:
                raise UsageError(f"GitHub repository not found: {repo}") from exc
            return f"could not verify {repo} on GitHub ({exc.friendly()}) — added anyway"
        return None

    def remove(self, ref: str) -> Source:
        source = self.resolve(ref)
        self.db.delete_source(source.id)
        return source

    def list_sources(self) -> list[Source]:
        return self.db.list_sources()

    def resolve(self, ref: str) -> Source:
        """Resolve ``ref`` as id, exact name, or unique name prefix."""
        sources = self.db.list_sources()
        if ref.isdigit():
            for s in sources:
                if str(s.id) == ref:
                    return s
        exact = [s for s in sources if s.name == ref]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise UsageError(f"ambiguous reference {ref!r} — matches {', '.join(s.name for s in exact)}")
        prefixes = [s for s in sources if s.name.startswith(ref)]
        if len(prefixes) == 1:
            return prefixes[0]
        if len(prefixes) > 1:
            raise UsageError(f"ambiguous reference {ref!r} — matches {', '.join(s.name for s in prefixes)}")
        raise UsageError(f"unknown source {ref!r} (see 'sentinel list')")

    # -- checking ---------------------------------------------------------
    def check(self, refs: list[str] | None = None) -> list[CheckResult]:
        """Check sources, persist snapshots/changes, and return per-source results."""
        sources = [self.resolve(ref) for ref in refs] if refs else self.db.list_sources(enabled_only=True)
        if not sources:
            raise UsageError("no sources configured — run 'sentinel add' first")

        results: list[CheckResult] = []
        for source in sources:
            results.append(self._check_one(source))
        return results

    def _check_one(self, source: Source) -> CheckResult:
        now = utc_now()
        monitor = get_monitor(source.kind)()
        try:
            observation = monitor.fetch(source, self.transport)
        except (FetchError, SentinelError) as exc:
            self._record_failure(source, exc, now)
            return CheckResult(source, ok=False, error=exc.friendly())
        except Exception as exc:  # noqa: BLE001 — never let one source crash a run
            self._record_failure(source, exc, now)
            return CheckResult(source, ok=False, error=f"unexpected error: {type(exc).__name__}: {exc}")

        previous = self.db.latest_snapshot(source.id)
        changes = monitor.diff(source, previous, observation) if previous else []
        first = previous is None

        if first or changes:
            self.db.record_snapshot(
                source.id,
                observation.fetched_at or now,
                observation.value,
                observation.state,
                observation.raw,
            )
        if changes:
            self.db.record_changes(source.id, now, changes)

        # Availability recovery: last check failed, this one succeeded.
        if source.last_status == "failed":
            recovered = ChangeDetector.availability(False, True)
            if recovered:
                self.db.record_changes(source.id, now, [recovered])
                changes = [recovered, *changes]

        self.db.record_check(source.id, now, True, None)
        self.db.set_check_result(source.id, True, None, now)
        return CheckResult(source, ok=True, observation=observation, changes=changes, first=first)

    def _record_failure(self, source: Source, exc: SentinelError, now: str) -> None:
        message = getattr(exc, "friendly", lambda: str(exc))()
        if source.last_status == "ok":
            offline = ChangeDetector.availability(True, False, error=message)
            if offline:
                self.db.record_changes(source.id, now, [offline])
        self.db.record_check(source.id, now, False, message)
        self.db.set_check_result(source.id, False, message, now)

    # -- reporting --------------------------------------------------------
    def status(self) -> dict:
        """Health overview + what could be updated."""
        rows = []
        for source in self.db.list_sources():
            snapshot = self.db.latest_snapshot(source.id)
            last_change = self.db.latest_change(source.id)
            monitor = get_monitor(source.kind)()
            rows.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "kind": source.kind,
                    "value": monitor.format_value(source, snapshot.value) if snapshot else "—",
                    "observed_at": snapshot.observed_at if snapshot else None,
                    "last_checked_at": source.last_checked_at,
                    "last_status": source.last_status,
                    "last_error": source.last_error,
                    "last_change": last_change.change.to_dict() if last_change else None,
                    "last_change_at": last_change.detected_at if last_change else None,
                }
            )
        plans = UpgradeService(self.transport).plan_all(self.db.list_sources())
        return {"sources": rows, "updates": [p.to_dict() for p in plans.plans], "skipped": plans.skipped}

    def history(self, ref: str, limit: int = 10) -> dict:
        source = self.resolve(ref)
        snapshots = self.db.list_snapshots(source.id, limit=limit)
        return {
            "source": source,
            "snapshots": [
                {
                    "observed_at": s.observed_at,
                    "value": s.value,
                }
                for s in snapshots
            ],
        }

    def show(self, ref: str) -> dict:
        source = self.resolve(ref)
        snapshot = self.db.latest_snapshot(source.id)
        changes = self.db.list_changes(source.id, limit=5)
        return {
            "source": source,
            "snapshot": snapshot,
            "changes": [{"detected_at": c.detected_at, **c.change.to_dict()} for c in changes],
        }

    # -- watch / update / upgrade ----------------------------------------
    def watch(self, interval: str, tick: callable) -> None:
        """Run *tick* immediately, then every *interval*. Blocks; Ctrl-C exits."""
        from sentinel.util import parse_interval

        if not self.db.list_sources(enabled_only=True):
            raise UsageError("no sources configured — run 'sentinel add' first")
        seconds = parse_interval(interval)
        Scheduler(float(seconds), tick).run()

    def upgrade(self, refs: list[str] | None = None) -> UpgradeReport:
        """Plan updates for all sources (or the selected ones). Never mutates."""
        sources = [self.resolve(ref) for ref in refs] if refs else self.db.list_sources(enabled_only=True)
        if not sources:
            raise UsageError("no sources configured — run 'sentinel add' first")
        return UpgradeService(self.transport).plan_all(sources)

    def apply_update(self, plan: UpdatePlan, allow_unverified: bool = False) -> UpdateResult:
        """Apply one update plan (caller must have obtained confirmation).

        Records the outcome in the ``updates`` audit table.
        """
        updaters = get_updaters(plan.kind)
        if not updaters:
            raise UsageError(f"no updater for {plan.kind} sources")
        result = updaters[0].apply(plan, self.transport, allow_unverified=allow_unverified)
        self.db.record_update(
            source_id=plan.source.id,
            tool=plan.tool,
            installed=plan.installed_version,
            latest=plan.latest_version,
            source_url=plan.source_url,
            performed_at=utc_now(),
            status=result.status,
        )
        return result

    def self_update(self) -> dict:
        return SelfUpdateService().check(self.transport)

"""The update system.

Two distinct capabilities live here:

* ``sentinel update``  — updating **Sentinel itself** (read-only reporting).
* ``sentinel upgrade`` — updating **software Sentinel manages** (planning and
  applying updates through registered :class:`~sentinel.updaters.base.Updater`
  implementations).

Upgrading is explicit and potentially destructive. Every updater must: prefer
official sources, verify downloads when checksums are available, require
explicit user confirmation, support ``--dry-run`` (planning never mutates
anything), and fail safely. Every applied update is recorded in the ``updates``
audit table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel import __version__
from sentinel.errors import FetchError, SentinelError
from sentinel.httpclient import Transport
from sentinel.models import Source, UpdatePlan
from sentinel.updaters import get_updaters
from sentinel.versions import compare

PYPI_JSON = "https://pypi.org/pypi/{name}/json"


@dataclass
class UpgradeReport:
    """Result of planning an upgrade run: what to do + what was skipped."""

    plans: list[UpdatePlan] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {name, kind, reason}

    def to_dict(self) -> dict:
        return {
            "plans": [p.to_dict() for p in self.plans],
            "skipped": self.skipped,
        }


class UpgradeService:
    """Plans upgrades across sources. Never mutates anything."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def plan_all(self, sources: list[Source]) -> UpgradeReport:
        report = UpgradeReport()
        for source in sources:
            updaters = get_updaters(source.kind)
            if not updaters:
                report.skipped.append(
                    {
                        "name": source.name,
                        "kind": source.kind,
                        "reason": "no updater for this source type (monitoring only)",
                    }
                )
                continue
            if not self._applicable(source):
                report.skipped.append(
                    {"name": source.name, "kind": source.kind, "reason": self._not_applicable_reason(source)}
                )
                continue
            for updater in updaters:
                try:
                    plan = updater.plan(source, self.transport)
                except (FetchError, SentinelError) as exc:
                    report.skipped.append(
                        {"name": source.name, "kind": source.kind, "reason": f"could not check: {exc.friendly()}"}
                    )
                    continue
                if plan is None:
                    continue
                if plan.noop:
                    report.skipped.append(
                        {"name": source.name, "kind": source.kind, "reason": plan.noop_reason}
                    )
                else:
                    report.plans.append(plan)
        return report

    @staticmethod
    def _applicable(source: Source) -> bool:
        if source.kind == "github":
            return bool((source.config.get("install_path") or "").strip())
        return True

    @staticmethod
    def _not_applicable_reason(source: Source) -> str:
        if source.kind == "github":
            return "no install path — re-add with 'sentinel add github … --install-path DIR' to enable updates"
        return "not updatable"


class SelfUpdateService:
    """Reports whether a newer Sentinel release exists on PyPI (best effort)."""

    # Only our own distribution is ever considered. Falling back to other
    # packages named "sentinel" would report updates that are not ours.
    DISTRIBUTION = "sentinel-cli"

    def check(self, transport: Transport) -> dict:
        current = __version__
        latest = None
        try:
            data = transport.get_json(PYPI_JSON.format(name=self.DISTRIBUTION))
            latest = str(data.get("info", {}).get("version", ""))
        except (FetchError, SentinelError):
            pass
        if not latest:
            return {
                "current": current,
                "latest": None,
                "available": False,
                "checked": False,
                "message": "Could not check for updates (offline or not published yet).",
            }
        c = compare(current, latest)
        available = bool(c is not None and c < 0)
        return {
            "current": current,
            "latest": latest,
            "available": available,
            "checked": True,
            "message": f"You're on the latest version ({current}).",
            "install_hint": f"pip install --upgrade {self.DISTRIBUTION}",
            "verified": False,
            "verify_note": (
                f"A package named {self.DISTRIBUTION!r} exists on PyPI, but Sentinel cannot "
                "prove it is this distribution. Verify before installing anything."
            ),
        }

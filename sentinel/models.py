"""Core data models shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.diffing import Change


@dataclass
class Source:
    """A monitored source as persisted in SQLite."""

    id: int
    kind: str  # github | http | api
    name: str
    config: dict
    enabled: bool = True
    created_at: str = ""
    last_checked_at: str | None = None
    last_status: str | None = None  # ok | failed | None (never checked)
    last_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "config": self.config,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
        }


@dataclass
class Observation:
    """What a monitor observed at a point in time."""

    value: str | None  # display value, e.g. "1.103.0", "200"
    state: dict  # structured state used for diffing
    raw: str | None = None  # truncated raw payload for `sentinel show`
    fetched_at: str = ""


@dataclass
class Snapshot:
    """A persisted observation."""

    id: int
    source_id: int
    observed_at: str
    value: str | None
    state: dict = field(default_factory=dict)
    raw: str | None = None


@dataclass
class StoredChange:
    """A change persisted to the database (Change + provenance)."""

    source_id: int
    detected_at: str
    change: Change


@dataclass
class CheckResult:
    """Outcome of checking one source."""

    source: Source
    ok: bool
    error: str | None = None
    observation: Observation | None = None
    changes: list[Change] = field(default_factory=list)
    first: bool = False  # first successful observation (baseline recorded)

    def to_dict(self) -> dict:
        return {
            "name": self.source.name,
            "kind": self.source.kind,
            "ok": self.ok,
            "error": self.error,
            "first": self.first,
            "value": self.observation.value if self.observation else None,
            "changes": [c.to_dict() for c in self.changes],
        }


@dataclass
class AssetRef:
    """A downloadable release asset."""

    name: str
    size: int | None = None
    url: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "size": self.size, "url": self.url}


@dataclass
class UpdatePlan:
    """What *would* happen for one piece of software (nothing has run yet).

    A ``noop`` plan carries a reason instead of actions (already up to date,
    no releases yet, …) and is reported as skipped.
    """

    tool: str
    source: Source
    kind: str
    installed_version: str | None = None
    latest_version: str | None = None
    source_url: str = ""
    verified: bool = False
    verify_note: str = ""
    assets: list[AssetRef] = field(default_factory=list)
    install_path: str = ""
    actions: list[str] = field(default_factory=list)
    checksums: dict = field(default_factory=dict)  # asset name -> {algo, hex}
    noop: bool = False
    noop_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "source": self.source.name,
            "kind": self.kind,
            "installed_version": self.installed_version,
            "latest_version": self.latest_version,
            "source_url": self.source_url,
            "verified": self.verified,
            "verify_note": self.verify_note,
            "assets": [a.to_dict() for a in self.assets],
            "install_path": self.install_path,
            "actions": self.actions,
            "checksums": self.checksums,
        }


@dataclass
class UpdateResult:
    """Outcome of applying one update plan."""

    source: Source
    ok: bool
    message: str
    status: str = "failed"  # downloaded | downloaded-unverified | blocked | failed | skipped
    installed_version: str | None = None
    latest_version: str | None = None
    verified: bool = False
    downloaded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source.name,
            "ok": self.ok,
            "message": self.message,
            "status": self.status,
            "installed_version": self.installed_version,
            "latest_version": self.latest_version,
            "verified": self.verified,
            "downloaded": self.downloaded,
        }

"""Monitor framework.

A :class:`Monitor` knows how to *observe* one kind of source (fetch current
state) and how to *diff* two observations into :class:`Change` objects.

Monitoring is deliberately separated from updating: monitors are passive.
Updaters (see ``sentinel/update.py``) are explicit and potentially
destructive — they are never invoked by a check.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sentinel.diffing import Change
from sentinel.httpclient import Transport
from sentinel.models import Observation, Source


class Monitor(ABC):
    """Base class for all source monitors."""

    kind: str = ""
    label: str = ""

    @abstractmethod
    def fetch(self, source: Source, transport: Transport) -> Observation:
        """Fetch the current state of *source*. Raises ``FetchError`` subclasses
        on network failures so one broken source never crashes a run."""

    @abstractmethod
    def diff(self, source: Source, previous: Observation | None, current: Observation) -> list[Change]:
        """Compare two observations and explain what changed."""

    @classmethod
    @abstractmethod
    def default_name(cls, config: dict) -> str:
        """A sensible display name for a config (repo, hostname, …)."""

    @classmethod
    def prompt(cls) -> dict:
        """Interactively collect a source config. Only used by ``sentinel add``."""
        raise NotImplementedError(f"{cls.kind} has no interactive prompt")

    def format_value(self, source: Source, value: str | None) -> str:
        """How to render an observation value in tables and history."""
        return value if value is not None else "—"


# ---------------------------------------------------------------------------
# Note: update-side interfaces (Updater, VersionProvider, Verifier) live in
# sentinel/updaters/ — monitoring and updating stay strictly separate.

"""Updater interfaces.

An :class:`Updater` knows how to *update* one kind of source — as opposed to
:class:`~sentinel.monitors.base.Monitor`, which only observes. Updaters are
explicitly destructive-capable: they download artifacts and write files, so
they must only run after explicit user confirmation, must expose a dry-run
(planning never touches disk beyond reading), and must fail safely when
verification fails.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from sentinel.httpclient import Transport
from sentinel.models import Source, UpdatePlan, UpdateResult


class Updater(ABC):
    """Base class for all source updaters."""

    kind: ClassVar[str] = ""
    label: ClassVar[str] = ""

    @abstractmethod
    def plan(self, source: Source, transport: Transport) -> UpdatePlan | None:
        """Inspect what *would* be done, without changing anything.

        Returns ``None`` when the updater does not apply, or an ``UpdatePlan``
        (possibly ``noop`` with a reason) describing the pending work.
        """

    @abstractmethod
    def apply(
        self,
        plan: UpdatePlan,
        transport: Transport,
        *,
        allow_unverified: bool = False,
    ) -> UpdateResult:
        """Execute the update. Callers must obtain explicit confirmation first."""


class VersionProvider(ABC):
    """Provides the *latest known* version of a piece of software.

    Implementations must only ever read from verified official sources.
    """

    @abstractmethod
    def latest_version(self, source: Source, transport: Transport) -> str | None:
        """Return the latest version string, or ``None`` if unknown."""

"""Updater registry.

New updaters register here without touching the core: implement
:class:`~sentinel.updaters.base.Updater`, register an instance, done.
"""

from __future__ import annotations

from sentinel.updaters.base import Updater


class Registry:
    """Holds the registered updaters."""

    def __init__(self) -> None:
        self._updaters: list[Updater] = []

    def register(self, updater: Updater) -> Updater:
        self._updaters.append(updater)
        return updater

    def get(self, kind: str) -> list[Updater]:
        return [u for u in self._updaters if u.kind == kind]

    def all(self) -> list[Updater]:
        return list(self._updaters)


_registry = Registry()


def register(updater: Updater) -> Updater:
    return _registry.register(updater)


def get_updaters(kind: str) -> list[Updater]:
    return _registry.get(kind)


def all_updaters() -> list[Updater]:
    return _registry.all()


# Importing the submodules registers the built-in updaters.
from sentinel.updaters import github_release  # noqa: F401 — registration side effects

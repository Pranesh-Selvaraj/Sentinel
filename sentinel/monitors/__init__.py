"""Monitor registry.

Additional source types (npm, PyPI, Docker, RSS, prices, …) register here
without touching the core: implement :class:`Monitor`, register it, done.
"""

from __future__ import annotations

from sentinel.errors import ConfigError
from sentinel.monitors.base import Monitor


class Registry:
    """Holds the monitor classes by kind."""

    def __init__(self) -> None:
        self._by_kind: dict[str, type[Monitor]] = {}

    def register(self, cls: type[Monitor]) -> type[Monitor]:
        self._by_kind[cls.kind] = cls
        return cls

    def get(self, kind: str) -> type[Monitor]:
        try:
            return self._by_kind[kind]
        except KeyError:
            known = ", ".join(sorted(self._by_kind)) or "none"
            raise ConfigError(f"unknown source type {kind!r} (available: {known})") from None

    def kinds(self) -> list[str]:
        return sorted(self._by_kind)


_registry = Registry()


def register(cls: type[Monitor]) -> type[Monitor]:
    return _registry.register(cls)


def get_monitor(kind: str) -> type[Monitor]:
    return _registry.get(kind)


def monitor_kinds() -> list[str]:
    return _registry.kinds()


# Importing the submodules registers the built-in monitors.
from sentinel.monitors import api, github, http  # noqa: F401 — registration side effects

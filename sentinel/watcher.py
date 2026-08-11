"""Watch mode scheduling.

A tiny, testable scheduler: run *tick* immediately, then every *interval*
seconds. Ctrl-C (KeyboardInterrupt) propagates to the CLI, which exits
cleanly.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class Scheduler:
    """Calls ``tick`` immediately, then every ``interval`` seconds."""

    def __init__(self, interval: float, tick: Callable[[], None]) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.interval = float(interval)
        self.tick = tick
        self._stop = threading.Event()

    def run(self) -> None:
        """Block until :meth:`stop` is called or the process is interrupted."""
        self.tick()
        while not self._stop.wait(self.interval):
            self.tick()

    def stop(self) -> None:
        self._stop.set()

"""The change/diff system.

Every monitor produces :class:`Change` objects describing what moved between
two observations. :class:`ChangeDetector` holds the reusable comparison
strategies (version, HTTP status, JSON field, content hash, scalar value,
availability) so comparison logic lives in one place instead of being
scattered across monitors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sentinel.util import short_hash
from sentinel.versions import compare

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class Change:
    """A single detected change between two observations.

    kind:        ``version`` | ``status`` | ``json`` | ``content`` |
                 ``scalar`` | ``availability`` | ``commit``
    previous:    previous value (rendered)
    current:     current value (rendered)
    description: explanation line(s); may contain ``\\n``
    severity:    ``info`` or ``warn``
    data:        extra structured info (e.g. the JSON field name)
    """

    kind: str
    previous: str
    current: str
    description: str = ""
    severity: str = "info"
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "previous": self.previous,
            "current": self.current,
            "description": self.description,
            "severity": self.severity,
            "data": self.data,
        }


def render_change(c: Change, indent: str = "  ") -> list[str]:
    """Render a change as indented lines suitable for terminal output.

    The first line always shows the value transition (``1.102.0 → 1.103.0``,
    ``HTTP 200 → 404``, …); following lines carry the explanation.
    """
    if c.kind == "status":
        lines = [f"HTTP {c.previous} → {c.current}"]
    elif c.kind == "json":
        lines = [f"{c.data.get('field', 'value')}:", f"{c.previous} → {c.current}"]
    else:
        lines = [f"{c.previous} → {c.current}"]
    if c.description:
        lines.extend(c.description.splitlines())
    return [f"{indent}{line}" for line in lines]


class ChangeDetector:
    """Reusable comparison strategies. Each returns ``None`` for no change."""

    @staticmethod
    def version(previous: str | None, current: str | None, label: str = "version") -> Change | None:
        """Version string transition, e.g. ``1.102.0 → 1.103.0``."""
        if previous is None or current is None or str(previous) == str(current):
            return None
        c = compare(previous, current)
        if c is None:
            desc = f"{label.capitalize()} changed"
            severity = "info"
        elif c < 0:
            desc = f"New {label} detected"
            severity = "info"
        else:
            desc = f"{label.capitalize()} rolled back"
            severity = "warn"
        return Change("version", str(previous), str(current), desc, severity)

    @staticmethod
    def status(previous: int | None, current: int | None) -> Change | None:
        """HTTP status transition, e.g. ``200 → 404`` (warn once non-2xx)."""
        if previous is None or current is None or previous == current:
            return None
        severity = "warn" if current >= 400 else "info"
        return Change("status", str(previous), str(current), "", severity)

    @staticmethod
    def json_field(field: str, previous, current) -> Change | None:
        """A single extracted JSON value changed, e.g. ``$.version``."""
        if previous == current:
            return None
        prev = "(none)" if previous is None else str(previous)
        cur = "(none)" if current is None else str(current)
        return Change("json", prev, cur, "", "info", {"field": field})

    @staticmethod
    def content(previous_hash: str | None, current_hash: str, description: str = "Page content changed") -> Change | None:
        """Content hash changed (websites, API bodies)."""
        if previous_hash == current_hash:
            return None
        prev = short_hash(previous_hash) if previous_hash else "—"
        cur = short_hash(current_hash)
        return Change("content", prev, cur, description, "info")

    @staticmethod
    def scalar(label: str, previous, current, unit: str | None = None) -> Change | None:
        """A scalar value changed, with a delta explanation when numeric
        (e.g. ``Price dropped by €20``). Future price monitoring uses this."""
        if previous == current:
            return None
        prev = str(previous)
        cur = str(current)
        pm = _NUMBER_RE.search(prev)
        cm = _NUMBER_RE.search(cur)
        desc = f"{label} changed"
        if pm and cm:
            delta = float(cm.group()) - float(pm.group())
            magnitude = f"{unit or ''}{abs(delta):g}"
            if delta < 0:
                desc = f"{label} dropped by {magnitude}"
            elif delta > 0:
                desc = f"{label} increased by {magnitude}"
        return Change("scalar", prev, cur, desc, "info", {"label": label})

    @staticmethod
    def availability(previous_online: bool, current_online: bool, error: str | None = None) -> Change | None:
        """A source became unreachable (or recovered)."""
        prev = "online" if previous_online else "offline"
        cur = "online" if current_online else "offline"
        if prev == cur:
            return None
        desc = "Source reachable again" if current_online else f"Source unreachable: {error or 'unknown error'}"
        return Change("availability", prev, cur, desc, "warn")

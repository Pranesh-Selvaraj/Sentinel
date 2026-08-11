"""Loose version parsing and comparison.

Sentinel deals with version strings from many ecosystems: ``1.102.0``,
``v1.4.0``, ``3.13.7``, ``2024.1.2``, ``1.0.0-beta.1``, ``2.4.0+build5``.
This module normalizes them into comparable tokens. It is intentionally
*loose*: when a string cannot be parsed we return ``None`` and callers fall
back to plain string comparison — never crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"\d+|[A-Za-z]+")


def _tokenize(segment: str) -> tuple:
    """Split ``"1a2"`` into ``(1, 'a', 2)`` — numbers as ints, letters as str."""
    return tuple(int(t) if t.isdigit() else t for t in _TOKEN_RE.findall(segment))


@dataclass(frozen=True)
class Version:
    """A parsed version string."""

    raw: str
    core: tuple
    pre: tuple | None = None

    @property
    def is_prerelease(self) -> bool:
        return self.pre is not None

    def __str__(self) -> str:
        return self.raw


def parse_version(value) -> Version | None:
    """Parse a version string.

    Returns ``None`` when the string is not version-like (e.g. ``"abc"``).
    Build metadata (``+build``) is ignored for comparison. A leading ``v`` is
    stripped.
    """
    if value is None:
        return None
    text = str(value).strip()
    text = re.sub(r"^[vV]", "", text)
    if not text or not re.search(r"[0-9A-Za-z]", text):
        return None
    if "+" in text:
        text = text.split("+", 1)[0]
    parts = text.split("-", 1)
    core = _tokenize(parts[0])
    if not core or not any(isinstance(t, int) for t in core):
        return None
    pre = _tokenize(parts[1]) if len(parts) > 1 else None
    if pre is not None and not pre:
        pre = None
    return Version(raw=str(value).strip(), core=core, pre=pre)


def _cmp_token(x, y) -> int:
    """Compare two tokens. Numeric identifiers sort below alphanumeric ones
    (semver rule), so ``1.0.0 < 1.0.0-rc.1``-style ordering works for the
    common ``-alpha/-beta/-rc`` ladder."""
    if isinstance(x, int) and isinstance(y, int):
        return (x > y) - (x < y)
    if isinstance(x, str) and isinstance(y, str):
        return (x > y) - (x < y)
    return -1 if isinstance(x, int) else 1


def compare(a, b) -> int | None:
    """Compare two version strings.

    Returns ``-1``/``0``/``1`` when both parse, ``None`` otherwise (callers
    fall back to string comparison).
    """
    va = a if isinstance(a, Version) else parse_version(a)
    vb = b if isinstance(b, Version) else parse_version(b)
    if va is None or vb is None:
        return None

    width = max(len(va.core), len(vb.core))
    for i in range(width):
        x = va.core[i] if i < len(va.core) else 0
        y = vb.core[i] if i < len(vb.core) else 0
        c = _cmp_token(x, y)
        if c:
            return c

    if va.pre is None and vb.pre is None:
        return 0
    if va.pre is None:
        return 1  # release > prerelease
    if vb.pre is None:
        return -1
    for x, y in zip(va.pre, vb.pre, strict=False):
        c = _cmp_token(x, y)
        if c:
            return c
    return (len(va.pre) > len(vb.pre)) - (len(va.pre) < len(vb.pre))

"""Small shared helpers: time, intervals, hashing, JSON paths, masking."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

UTC = dt.timezone.utc


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string, e.g. ``2026-08-10T05:48:47Z``."""
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_time(iso: str | None, fmt: str = "%b %d %H:%M", include_year: bool = False) -> str:
    """Render a stored ISO timestamp in local time. Falls back to the raw string."""
    if not iso:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    local = parsed.astimezone()
    if include_year and local.year != dt.datetime.now().year:
        fmt = f"{fmt} %Y"
    return local.strftime(fmt)


def clock_time() -> str:
    """Current local time as ``HH:MM`` for watch-mode lines."""
    return dt.datetime.now().strftime("%H:%M")


_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(s: str) -> int:
    """Parse a duration like ``30s``, ``10m``, ``1h``, ``1h30m`` or plain seconds."""
    s = (s or "").strip().lower()
    if s.isdigit():
        value = int(s)
        if value > 0:
            return value
        raise ValueError(f"invalid interval: {s!r}")
    total = 0
    matched = False
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([smhd])", s):
        total += int(float(m.group(1)) * _INTERVAL_UNITS[m.group(2)])
        matched = True
    if not matched or total <= 0:
        raise ValueError(f"invalid interval: {s!r}")
    return total


def format_interval(seconds: int) -> str:
    """Render seconds compactly, e.g. ``10m``, ``1h30m``, ``45s``."""
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m}m" if m else f"{h}h"
    if m:
        return f"{m}m" if not s else f"{m}m{s}s"
    return f"{s}s"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short_hash(hexdigest: str, n: int = 8) -> str:
    return hexdigest[:n]


def truncate(text: str, n: int = 4000) -> str:
    if len(text) <= n:
        return text
    return text[: n - 3] + "..."


_JSON_PATH_TOKEN = re.compile(r"[^.\[]+|\[\d+\]")


def resolve_jpath(data, path: str | None):
    """Resolve a small JSONPath subset against parsed JSON.

    Supports ``$.a.b``, ``$.a[0].b``, ``a.b``, ``[0].name`` and ``$`` (root).
    Raises :class:`KeyError` when a path element does not exist.
    """
    path = (path or "$").strip()
    if not path or path == "$":
        return data
    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$["):
        path = path[1:]
    elif path.startswith("$"):
        path = path[1:]
    cur = data
    for raw_tok in _JSON_PATH_TOKEN.findall(path):
        if raw_tok.startswith("["):
            tok = raw_tok[1:-1]
        else:
            tok = raw_tok
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            raise KeyError(f"path element {raw_tok!r} not found in response")
    return cur


_SECRET_KEYS = ("token", "secret", "key", "password", "authorization", "auth", "api_key", "apikey")


def mask_secrets(config: dict) -> dict:
    """Return a copy of a config dict with credential-looking values masked.

    Used before printing configuration to a terminal. Header values that are
    ``${ENV_VAR}`` references are *not* secrets themselves and stay visible.
    """
    out: dict = {}
    for k, v in config.items():
        if isinstance(v, dict):
            out[k] = mask_secrets(v)
        elif isinstance(v, list):
            out[k] = [mask_secrets(item) if isinstance(item, dict) else item for item in v]
        elif isinstance(v, str) and not v.startswith("${") and any(s in k.lower() for s in _SECRET_KEYS) and v:
            out[k] = "***"
        else:
            out[k] = v
    return out


def json_dumps_compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def human_size(n: int | None) -> str:
    """Render a byte count compactly, e.g. ``88.4 MB``."""
    if n is None:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def safe_component(s: str) -> str:
    """Sanitize a string for use as a single filesystem path component."""
    cleaned = re.sub(r"[^A-Za-z0-9._+\-]", "_", s)
    return cleaned.strip("._") or "artifact"

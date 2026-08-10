"""Sentinel exception hierarchy.

All expected, user-facing failures derive from :class:`SentinelError` so the
CLI can render them cleanly instead of dumping a traceback.
"""

from __future__ import annotations


class SentinelError(Exception):
    """Base class for all expected Sentinel errors."""


class ConfigError(SentinelError):
    """Invalid configuration (config.toml, source config, …)."""


class UsageError(SentinelError):
    """The user asked for something invalid (unknown source, bad args)."""


class AbortError(SentinelError):
    """The user aborted an interactive flow (Ctrl-C / q / EOF)."""


class FetchError(SentinelError):
    """A network fetch failed. Carries how many retries were attempted."""

    def __init__(self, message: str = "", retries_used: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.retries_used = retries_used

    def friendly(self) -> str:
        """Human-readable message, including retry info when relevant."""
        msg = self.message or self.__class__.__name__
        if self.retries_used:
            n = self.retries_used
            msg += f" (after {n} retr{'y' if n == 1 else 'ies'})"
        return msg


class FetchTimeout(FetchError):
    """The connection or response timed out."""

    def __init__(self, url: str = "", retries_used: int = 0) -> None:
        super().__init__("Connection timeout", retries_used)
        self.url = url

    def friendly(self) -> str:
        base = f"Connection timeout for {self.url}" if self.url else "Connection timeout"
        if self.retries_used:
            base += f" (after {self.retries_used} retries)"
        return base


class FetchConnection(FetchError):
    """DNS / connection-level failure."""

    def __init__(self, detail: str = "", retries_used: int = 0) -> None:
        super().__init__(f"Connection error: {detail}" if detail else "Connection error", retries_used)
        self.detail = detail


class FetchHTTP(FetchError):
    """The server answered with a non-2xx HTTP status."""

    def __init__(self, status: int, body: bytes = b"", url: str = "", retries_used: int = 0) -> None:
        super().__init__(f"HTTP {status}", retries_used)
        self.status = status
        self.body = body[:65536]
        self.url = url

    def friendly(self) -> str:
        # GitHub and many APIs include a JSON {"message": ...} on errors.
        try:
            import json

            payload = json.loads(self.body.decode("utf-8", "replace"))
            if isinstance(payload, dict) and payload.get("message"):
                return f"HTTP {self.status}: {payload['message']}"
        except (ValueError, UnicodeDecodeError):
            pass
        msg = f"HTTP {self.status}"
        if self.retries_used:
            msg += f" (after {self.retries_used} retries)"
        return msg


class FetchRateLimited(FetchError):
    """The API refused the request because a rate limit was exhausted."""

    def __init__(self, reset_epoch: int | None = None, retries_used: int = 0) -> None:
        super().__init__("API rate limit exceeded", retries_used)
        self.reset_epoch = reset_epoch

    def friendly(self) -> str:
        msg = "API rate limit exceeded"
        if self.reset_epoch:
            try:
                import datetime as dt

                when = dt.datetime.fromtimestamp(self.reset_epoch, dt.timezone.utc).strftime("%H:%M UTC")
                msg += f" — resets at {when}"
            except (OverflowError, OSError, ValueError):
                pass
        msg += " (set GITHUB_TOKEN to increase your limit)"
        return msg


class FetchInvalidJSON(FetchError):
    """The response body was not valid JSON."""

    def __init__(self, url: str = "") -> None:
        super().__init__("Invalid JSON response" + (f" from {url}" if url else ""))
        self.url = url


class NotSupportedError(SentinelError):
    """An updater cannot (or may not) perform the requested update."""

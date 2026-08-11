"""HTTP transport with timeouts, retries and typed errors.

Everything network-facing goes through :class:`Transport`, which makes
retry/timeout behavior uniform and lets tests substitute a fake transport
without touching ``urllib``.
"""

from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from sentinel import __version__
from sentinel.errors import (
    FetchConnection,
    FetchError,
    FetchHTTP,
    FetchInvalidJSON,
    FetchRateLimited,
    FetchTimeout,
)

RETRYABLE_STATUS = {500, 502, 503, 504}


@dataclass
class Response:
    """A normalized HTTP response."""

    status: int
    headers: dict  # lowercase keys
    body: bytes
    url: str


class Transport:
    """Small wrapper around ``urllib`` with retries and typed failures."""

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 3,
        user_agent: str = f"sentinel/{__version__}",
        github_token: str | None = None,
        backoff: float = 0.5,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.github_token = github_token
        self.backoff = backoff

    # -- public API -------------------------------------------------------
    def get(self, url: str, headers: dict | None = None) -> Response:
        # Only http(s) is ever opened — file:, ftp:, custom schemes and
        # other surprises are rejected up front (defense against
        # misconfigured/local-file reads via user-supplied URLs).
        scheme = urllib.parse.urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            raise FetchError(f"unsupported URL scheme {scheme!r} — only http/https are allowed")
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(url, headers=request_headers, method="GET")  # noqa: S310 — scheme guarded above

        attempts = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310  # nosec B310 — scheme guarded above
                    body = resp.read()
                    return Response(
                        status=resp.status,
                        headers={k.lower(): v for k, v in resp.headers.items()},
                        body=body,
                        url=resp.geturl(),
                    )
            except urllib.error.HTTPError as exc:
                body = exc.read(65536) if hasattr(exc, "read") else b""
                lowered = {k.lower(): v for k, v in exc.headers.items()}
                if exc.code == 403 and lowered.get("x-ratelimit-remaining") == "0":
                    # Rate limits are not transient; retrying would waste attempts.
                    reset = lowered.get("x-ratelimit-reset")
                    raise FetchRateLimited(
                        reset_epoch=int(reset) if reset and reset.isdigit() else None,
                        retries_used=attempts,
                    ) from exc
                if exc.code in RETRYABLE_STATUS and attempts < self.retries:
                    attempts += 1
                    time.sleep(self._backoff(attempts))
                    continue
                raise FetchHTTP(exc.code, body, url, retries_used=attempts) from exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if attempts < self.retries:
                    attempts += 1
                    time.sleep(self._backoff(attempts))
                    continue
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    raise FetchTimeout(url, retries_used=attempts) from exc
                detail = str(reason) or repr(reason)
                if (
                    isinstance(reason, ConnectionError)
                    or "getaddrinfo" in detail
                    or "connection" in detail.lower()
                ):
                    raise FetchConnection(detail, retries_used=attempts) from exc
                raise FetchError(detail, retries_used=attempts) from exc

    def get_json(self, url: str, headers: dict | None = None):
        """GET and parse JSON. Raises :class:`FetchInvalidJSON` on bad bodies."""
        resp = self.get(url, headers)
        try:
            return json.loads(resp.body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            raise FetchInvalidJSON(url) from None

    # -- helpers ----------------------------------------------------------
    def _backoff(self, attempt: int) -> float:
        # jitter is for load spreading, not cryptography
        return self.backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.25)  # nosec B311

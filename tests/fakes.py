"""Test doubles: a fake HTTP transport so tests never touch the network."""

from __future__ import annotations

import json

from sentinel.errors import FetchError, FetchInvalidJSON
from sentinel.httpclient import Response


def make_response(
    status: int, body: bytes | str = b"", headers: dict | None = None, url: str = "http://fake"
) -> Response:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return Response(status=status, headers=headers or {}, body=body, url=url)


def make_json_response(status: int, payload, headers: dict | None = None) -> Response:
    return make_response(status, json.dumps(payload), headers)


class FakeTransport:
    """Routes exact URLs to canned responses or exceptions.

    Unrouted URLs raise FetchError unless *default* is given.
    """

    def __init__(self, routes: dict | None = None, default=None) -> None:
        self.routes = dict(routes or {})
        self.default = default
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, headers: dict | None = None) -> Response:
        self.calls.append((url, headers))
        if url in self.routes:
            response = self.routes[url]
            if isinstance(response, Exception):
                raise response
            return response
        if self.default is not None:
            if isinstance(self.default, Exception):
                raise self.default
            return self.default
        raise FetchError(f"no fake route for {url}")

    def get_json(self, url: str, headers: dict | None = None):
        # Mirror the real Transport: non-JSON bodies raise FetchInvalidJSON.
        try:
            return json.loads(self.get(url, headers).body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise FetchInvalidJSON(url) from None

    def route(self, url: str, response) -> FakeTransport:
        self.routes[url] = response
        return self

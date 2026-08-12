"""Tests for the real HTTP transport: retries, typed errors, scheme guard."""

from __future__ import annotations

import socket
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from unittest import mock

from sentinel.errors import FetchConnection, FetchError, FetchHTTP, FetchRateLimited, FetchTimeout
from sentinel.httpclient import Transport


class FakeResponse:
    def __init__(self, status=200, body=b"ok", headers=None, url="https://example.com/"):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self._url = url

    def read(self):
        return self.body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_http_error(status: int, headers=None, body=b'{"message": "nope"}'):
    exc = urllib.error.HTTPError("https://example.com/", status, f"err {status}", headers or {}, None)
    exc.read = lambda size=65536: body  # type: ignore[method-assign]
    return exc


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.transport = Transport(retries=3, backoff=0)

    def run(self, result=None):
        # Keep the mock active for the whole test method.
        with mock.patch("urllib.request.urlopen") as self.urlopen:
            super().run(result)

    def test_successful_get(self):
        self.urlopen.return_value = FakeResponse(body=b"hello")
        resp = self.transport.get("https://example.com/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, b"hello")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_retries_5xx_then_succeeds(self):
        self.urlopen.side_effect = [
            fake_http_error(503),
            fake_http_error(502),
            FakeResponse(body=b"ok"),
        ]
        resp = self.transport.get("https://example.com/")
        self.assertEqual(resp.body, b"ok")
        self.assertEqual(self.urlopen.call_count, 3)

    def test_retries_429_then_succeeds(self):
        self.urlopen.side_effect = [
            fake_http_error(429, headers={"Retry-After": "1"}),
            FakeResponse(body=b"ok"),
        ]
        resp = self.transport.get("https://example.com/")
        self.assertEqual(resp.body, b"ok")
        self.assertEqual(self.urlopen.call_count, 2)

    def test_429_gives_up_after_retries(self):
        self.urlopen.side_effect = fake_http_error(429, headers={"Retry-After": "1"})
        with self.assertRaises(FetchHTTP) as ctx:
            self.transport.get("https://example.com/")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.retries_used, 3)
        self.assertEqual(self.urlopen.call_count, 4)  # initial + 3 retries

    def test_retry_after_seconds_is_honored(self):
        self.urlopen.side_effect = [
            fake_http_error(429, headers={"Retry-After": "2"}),
            FakeResponse(body=b"ok"),
        ]
        with mock.patch("sentinel.httpclient.time.sleep") as sleep:
            self.transport.get("https://example.com/")
        sleep.assert_called_once_with(2.0)

    def test_retry_after_http_date_is_honored(self):
        from email.utils import format_datetime

        when = format_datetime(datetime.now(UTC) + timedelta(minutes=1))
        self.urlopen.side_effect = [
            fake_http_error(503, headers={"Retry-After": when}),
            FakeResponse(body=b"ok"),
        ]
        with mock.patch("sentinel.httpclient.time.sleep") as sleep:
            self.transport.get("https://example.com/")
        delay = sleep.call_args.args[0]
        self.assertGreater(delay, 0)
        self.assertLessEqual(delay, 60.0)

    def test_retry_after_is_capped(self):
        self.urlopen.side_effect = [
            fake_http_error(429, headers={"Retry-After": "3600"}),
            FakeResponse(body=b"ok"),
        ]
        with mock.patch("sentinel.httpclient.time.sleep") as sleep:
            self.transport.get("https://example.com/")
        sleep.assert_called_once_with(60.0)

    def test_garbage_retry_after_falls_back_to_backoff(self):
        self.urlopen.side_effect = [
            fake_http_error(503, headers={"Retry-After": "next tuesday, maybe"}),
            FakeResponse(body=b"ok"),
        ]
        with mock.patch("sentinel.httpclient.time.sleep") as sleep:
            self.transport.get("https://example.com/")
        # Exponential backoff with backoff=0: only the jitter remains.
        self.assertLess(sleep.call_args.args[0], 0.25)

    def test_429_without_retry_after_uses_backoff(self):
        self.urlopen.side_effect = [
            fake_http_error(429),
            FakeResponse(body=b"ok"),
        ]
        with mock.patch("sentinel.httpclient.time.sleep") as sleep:
            self.transport.get("https://example.com/")
        self.assertLess(sleep.call_args.args[0], 0.25)

    def test_retries_connection_error_then_succeeds(self):
        self.urlopen.side_effect = [
            urllib.error.URLError(ConnectionResetError("boom")),
            urllib.error.URLError(socket.gaierror(-2, "getaddrinfo failed")),
            FakeResponse(body=b"ok"),
        ]
        resp = self.transport.get("https://example.com/")
        self.assertEqual(resp.body, b"ok")
        self.assertEqual(self.urlopen.call_count, 3)

    def test_gives_up_after_retries_on_connection_error(self):
        self.urlopen.side_effect = urllib.error.URLError(ConnectionResetError("boom"))
        with self.assertRaises(FetchConnection) as ctx:
            self.transport.get("https://example.com/")
        self.assertEqual(ctx.exception.retries_used, 3)
        self.assertEqual(self.urlopen.call_count, 4)  # initial + 3 retries

    def test_timeout_after_retries(self):
        self.urlopen.side_effect = urllib.error.URLError(TimeoutError("timed out"))
        with self.assertRaises(FetchTimeout) as ctx:
            self.transport.get("https://example.com/")
        self.assertEqual(ctx.exception.retries_used, 3)

    def test_404_not_retried(self):
        self.urlopen.side_effect = fake_http_error(404)
        with self.assertRaises(FetchHTTP) as ctx:
            self.transport.get("https://example.com/")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.retries_used, 0)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_rate_limit_not_retried(self):
        self.urlopen.side_effect = fake_http_error(403, headers={"X-RateLimit-Remaining": "0"})
        with self.assertRaises(FetchRateLimited):
            self.transport.get("https://example.com/")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_403_without_exhausted_rate_limit_is_not_retried(self):
        self.urlopen.side_effect = fake_http_error(403, headers={"X-RateLimit-Remaining": "5"})
        with self.assertRaises(FetchHTTP) as ctx:
            self.transport.get("https://example.com/")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_rejects_file_scheme(self):
        with self.assertRaises(FetchError) as ctx:
            self.transport.get("file:///etc/passwd")
        self.assertIn("scheme", str(ctx.exception))
        self.assertEqual(self.urlopen.call_count, 0)

    def test_rejects_ftp_scheme(self):
        with self.assertRaises(FetchError):
            self.transport.get("ftp://example.com/file")
        self.assertEqual(self.urlopen.call_count, 0)

    def test_get_json(self):
        self.urlopen.return_value = FakeResponse(body=b'{"version": "1.2.3"}')
        data = self.transport.get_json("https://example.com/")
        self.assertEqual(data, {"version": "1.2.3"})


if __name__ == "__main__":
    unittest.main()

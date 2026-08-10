import unittest

from sentinel.models import Observation, Source
from sentinel.monitors.http import HttpMonitor
from tests.fakes import FakeTransport, make_response

HTML = b"<html><head><title>Example Domain</title></head><body>Hello</body></html>"


def source(url="https://example.com") -> Source:
    return Source(id=1, kind="http", name="example.com", config={"url": url})


class HttpFetchTests(unittest.TestCase):
    def setUp(self):
        self.monitor = HttpMonitor()
        self.transport = FakeTransport({"https://example.com": make_response(200, HTML, {"content-type": "text/html"})})

    def test_fetch_status_and_title(self):
        obs = self.monitor.fetch(source(), self.transport)
        self.assertEqual(obs.value, "200")
        self.assertEqual(obs.state["status"], 200)
        self.assertEqual(obs.state["title"], "Example Domain")
        self.assertEqual(len(obs.state["content_sha256"]), 64)

    def test_format_value(self):
        self.assertEqual(self.monitor.format_value(source(), "200"), "HTTP 200")


class HttpDiffTests(unittest.TestCase):
    def setUp(self):
        self.monitor = HttpMonitor()

    def test_status_change(self):
        prev = Observation("200", {"status": 200, "content_sha256": "a" * 64})
        cur = Observation("404", {"status": 404, "content_sha256": "b" * 64})
        changes = self.monitor.diff(source(), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "status")
        self.assertEqual(changes[0].severity, "warn")

    def test_content_change(self):
        prev = Observation("200", {"status": 200, "content_sha256": "a" * 64})
        cur = Observation("200", {"status": 200, "content_sha256": "b" * 64})
        changes = self.monitor.diff(source(), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "content")
        self.assertEqual(changes[0].description, "Page content changed")

    def test_no_change(self):
        prev = Observation("200", {"status": 200, "content_sha256": "a" * 64})
        cur = Observation("200", {"status": 200, "content_sha256": "a" * 64})
        self.assertEqual(self.monitor.diff(source(), prev, cur), [])

    def test_baseline(self):
        cur = Observation("200", {"status": 200, "content_sha256": "a" * 64})
        self.assertEqual(self.monitor.diff(source(), None, cur), [])


if __name__ == "__main__":
    unittest.main()

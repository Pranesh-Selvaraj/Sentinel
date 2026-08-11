import unittest
from unittest import mock

from sentinel.errors import FetchInvalidJSON
from sentinel.models import Observation, Source
from sentinel.monitors.api import ApiMonitor
from tests.fakes import FakeTransport, make_json_response, make_response


def source(config: dict) -> Source:
    return Source(id=1, kind="api", name="api.example.com", config=config)


class ApiFetchTests(unittest.TestCase):
    def setUp(self):
        self.monitor = ApiMonitor()

    def test_fetch_with_jpath(self):
        transport = FakeTransport(
            {
                "https://api.example.com/version": make_json_response(200, {"version": "1.4.2"}),
            }
        )
        obs = self.monitor.fetch(
            source({"url": "https://api.example.com/version", "jpath": "$.version"}), transport
        )
        self.assertEqual(obs.value, "1.4.2")
        self.assertEqual(obs.state["status"], 200)

    def test_nested_jpath(self):
        transport = FakeTransport(
            {
                "https://api.example.com/x": make_json_response(200, {"data": {"items": [{"id": 7}]}}),
            }
        )
        obs = self.monitor.fetch(
            source({"url": "https://api.example.com/x", "jpath": "$.data.items[0].id"}), transport
        )
        self.assertEqual(obs.value, "7")

    def test_missing_field_is_none(self):
        transport = FakeTransport(
            {
                "https://api.example.com/x": make_json_response(200, {"other": 1}),
            }
        )
        obs = self.monitor.fetch(
            source({"url": "https://api.example.com/x", "jpath": "$.version"}), transport
        )
        self.assertIsNone(obs.value)

    def test_invalid_json_raises(self):
        transport = FakeTransport(
            {
                "https://api.example.com/x": make_response(200, b"<html>not json</html>"),
            }
        )
        with self.assertRaises(FetchInvalidJSON):
            self.monitor.fetch(source({"url": "https://api.example.com/x", "jpath": "$.v"}), transport)

    def test_no_jpath_tracks_body_hash(self):
        transport = FakeTransport(
            {
                "https://api.example.com/x": make_json_response(200, {"a": 1}),
            }
        )
        obs = self.monitor.fetch(source({"url": "https://api.example.com/x"}), transport)
        self.assertEqual(obs.value, "200")
        self.assertIn("body_sha256", obs.state)

    def test_headers_env_expansion(self):
        transport = FakeTransport(
            {
                "https://api.example.com/x": make_json_response(200, {"ok": True}),
            }
        )
        with mock.patch.dict("os.environ", {"API_KEY": "secret-value"}, clear=False):
            self.monitor.fetch(
                source({"url": "https://api.example.com/x", "headers": {"X-Api-Key": "${API_KEY}"}}),
                transport,
            )
        sent_headers = transport.calls[0][1]
        self.assertEqual(sent_headers["X-Api-Key"], "secret-value")

    def test_format_value_with_jpath(self):
        src = source({"url": "https://api.example.com/x", "jpath": "$.version"})
        self.assertEqual(self.monitor.format_value(src, "1.4.2"), "1.4.2")

    def test_format_value_without_jpath(self):
        src = source({"url": "https://api.example.com/x"})
        self.assertEqual(self.monitor.format_value(src, "200"), "HTTP 200")


class ApiDiffTests(unittest.TestCase):
    def setUp(self):
        self.monitor = ApiMonitor()

    def test_json_value_change(self):
        src = source({"url": "u", "jpath": "$.version"})
        prev = Observation("1.4.2", {"status": 200, "jpath": "$.version", "value": "1.4.2"})
        cur = Observation("1.5.0", {"status": 200, "jpath": "$.version", "value": "1.5.0"})
        changes = self.monitor.diff(src, prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "json")
        self.assertEqual(changes[0].data["field"], "$.version")

    def test_json_no_change(self):
        src = source({"url": "u", "jpath": "$.version"})
        prev = Observation("1.5.0", {"status": 200, "value": "1.5.0"})
        cur = Observation("1.5.0", {"status": 200, "value": "1.5.0"})
        self.assertEqual(self.monitor.diff(src, prev, cur), [])

    def test_status_change_wins(self):
        src = source({"url": "u", "jpath": "$.version"})
        prev = Observation("200", {"status": 200, "value": "1.5.0"})
        cur = Observation("404", {"status": 404, "value": None})
        changes = self.monitor.diff(src, prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "status")

    def test_body_change_without_jpath(self):
        src = source({"url": "u"})
        prev = Observation("200", {"status": 200, "body_sha256": "a" * 64})
        cur = Observation("200", {"status": 200, "body_sha256": "b" * 64})
        changes = self.monitor.diff(src, prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "content")
        self.assertEqual(changes[0].description, "Response body changed")


if __name__ == "__main__":
    unittest.main()

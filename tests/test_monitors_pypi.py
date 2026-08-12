"""Tests for the PyPI package monitor."""

import unittest
from unittest import mock

from sentinel.errors import ConfigError, FetchInvalidJSON
from sentinel.models import Observation, Source
from sentinel.monitors.pypi import PyPIMonitor
from tests.fakes import FakeTransport, make_json_response, make_response

API = "https://pypi.org/pypi/requests/json"


def source(config: dict) -> Source:
    return Source(id=1, kind="pypi", name="requests", config=config)


def pypi_payload(version: str = "2.32.3", name: str = "requests") -> dict:
    return {
        "info": {"name": name, "version": version, "summary": "Python HTTP for Humans."},
        "urls": [
            {"upload_time": "2024-05-29T09:05:12", "upload_time_iso_8601": "2024-05-29T09:05:12.000000Z"}
        ],
        "releases": {},
    }


class PyPIFetchTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.transport.route(API, make_json_response(200, pypi_payload()))

    def test_fetch_latest_version(self):
        obs = PyPIMonitor().fetch(source({"name": "requests", "monitor": "release"}), self.transport)
        self.assertEqual(obs.value, "2.32.3")
        self.assertEqual(obs.state["version"], "2.32.3")
        self.assertEqual(obs.state["name"], "requests")
        self.assertEqual(obs.state["released"], "2024-05-29T09:05:12.000000Z")
        self.assertIn("2.32.3", obs.raw)

    def test_fetch_invalid_package_name(self):
        with self.assertRaises(ConfigError):
            PyPIMonitor().fetch(source({"name": "../etc", "monitor": "release"}), self.transport)

    def test_fetch_non_json_body(self):
        self.transport.route(API, make_response(200, "<html>proxy error</html>"))
        with self.assertRaises(FetchInvalidJSON):
            PyPIMonitor().fetch(source({"name": "requests", "monitor": "release"}), self.transport)

    def test_fetch_missing_info(self):
        self.transport.route(API, make_json_response(200, {}))
        obs = PyPIMonitor().fetch(source({"name": "requests", "monitor": "release"}), self.transport)
        self.assertIsNone(obs.value)


class PyPIDiffTests(unittest.TestCase):
    def test_new_release_detected(self):
        prev = Observation(value="2.32.3", state={"version": "2.32.3"})
        cur = Observation(value="2.33.0", state={"version": "2.33.0"})
        changes = PyPIMonitor().diff(source({"name": "requests"}), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "version")
        self.assertIn("New release", changes[0].description)

    def test_no_change(self):
        prev = Observation(value="2.32.3", state={"version": "2.32.3"})
        cur = Observation(value="2.32.3", state={"version": "2.32.3"})
        self.assertEqual(PyPIMonitor().diff(source({"name": "requests"}), prev, cur), [])

    def test_first_observation_is_baseline(self):
        cur = Observation(value="2.32.3", state={"version": "2.32.3"})
        self.assertEqual(PyPIMonitor().diff(source({"name": "requests"}), None, cur), [])


class PyPINamingTests(unittest.TestCase):
    def test_default_name(self):
        self.assertEqual(PyPIMonitor.default_name({"name": "requests"}), "requests")

    def test_format_value(self):
        monitor = PyPIMonitor()
        self.assertEqual(monitor.format_value(source({}), "1.0.0"), "1.0.0")
        self.assertEqual(monitor.format_value(source({}), None), "—")

    def test_prompt(self):
        with mock.patch("sentinel.monitors.pypi.input_text", side_effect=["bad name!", "requests"]):
            config = PyPIMonitor.prompt()
        self.assertEqual(config, {"name": "requests", "monitor": "release"})


if __name__ == "__main__":
    unittest.main()

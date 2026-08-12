"""Tests for the npm package monitor."""

import unittest
from unittest import mock

from sentinel.errors import ConfigError, FetchInvalidJSON
from sentinel.models import Observation, Source
from sentinel.monitors.npm import NpmMonitor
from tests.fakes import FakeTransport, make_json_response, make_response

API = "https://registry.npmjs.org/express"


def source(config: dict) -> Source:
    return Source(id=1, kind="npm", name="express", config=config)


def npm_payload(version: str = "5.1.0", name: str = "express") -> dict:
    return {
        "name": name,
        "dist-tags": {"latest": version},
        "modified": "2025-06-20T00:00:00.000Z",
        "description": "Fast, unopinionated, minimalist web framework",
        "homepage": "https://expressjs.com",
    }


class NpmFetchTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.transport.route(API, make_json_response(200, npm_payload()))

    def test_fetch_latest_version(self):
        obs = NpmMonitor().fetch(source({"name": "express", "monitor": "release"}), self.transport)
        self.assertEqual(obs.value, "5.1.0")
        self.assertEqual(obs.state["version"], "5.1.0")
        self.assertEqual(obs.state["name"], "express")
        self.assertEqual(obs.state["modified"], "2025-06-20T00:00:00.000Z")
        self.assertIn("5.1.0", obs.raw)

    def test_fetch_invalid_package_name(self):
        with self.assertRaises(ConfigError):
            NpmMonitor().fetch(source({"name": "a b", "monitor": "release"}), self.transport)

    def test_fetch_non_json_body(self):
        self.transport.route(API, make_response(200, "rate limited"))
        with self.assertRaises(FetchInvalidJSON):
            NpmMonitor().fetch(source({"name": "express", "monitor": "release"}), self.transport)

    def test_fetch_without_dist_tags(self):
        self.transport.route(API, make_json_response(200, {"name": "express"}))
        obs = NpmMonitor().fetch(source({"name": "express", "monitor": "release"}), self.transport)
        self.assertIsNone(obs.value)


class NpmDiffTests(unittest.TestCase):
    def test_new_release_detected(self):
        prev = Observation(value="5.1.0", state={"version": "5.1.0"})
        cur = Observation(value="5.2.0", state={"version": "5.2.0"})
        changes = NpmMonitor().diff(source({"name": "express"}), prev, cur)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, "version")
        self.assertIn("New release", changes[0].description)

    def test_rollback_warns(self):
        prev = Observation(value="5.2.0", state={"version": "5.2.0"})
        cur = Observation(value="5.1.0", state={"version": "5.1.0"})
        changes = NpmMonitor().diff(source({"name": "express"}), prev, cur)
        self.assertEqual(changes[0].severity, "warn")
        self.assertIn("rolled back", changes[0].description)

    def test_no_change(self):
        prev = Observation(value="5.1.0", state={"version": "5.1.0"})
        cur = Observation(value="5.1.0", state={"version": "5.1.0"})
        self.assertEqual(NpmMonitor().diff(source({"name": "express"}), prev, cur), [])


class NpmNamingTests(unittest.TestCase):
    def test_default_name(self):
        self.assertEqual(NpmMonitor.default_name({"name": "express"}), "express")

    def test_prompt(self):
        with mock.patch("sentinel.monitors.npm.input_text", side_effect=["not valid!", "express"]):
            config = NpmMonitor.prompt()
        self.assertEqual(config, {"name": "express", "monitor": "release"})


if __name__ == "__main__":
    unittest.main()

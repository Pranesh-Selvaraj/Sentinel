import tempfile
import unittest
from pathlib import Path

from sentinel.app import SentinelApp
from sentinel.errors import FetchTimeout, UsageError
from tests.fakes import FakeTransport, make_json_response, make_response

GITHUB_API = "https://api.github.com/repos/microsoft/vscode"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.transport = FakeTransport()
        self.app = SentinelApp(config_dir=self.dir, transport=self.transport)

    def tearDown(self):
        self.app.close()

    def add_vscode(self):
        self.transport.route(f"{GITHUB_API}", make_json_response(200, {"full_name": "microsoft/vscode"}))
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {"tag_name": "1.102.0", "name": "1.102.0", "assets": []}),
        )
        return self.app.add("github", {"repo": "microsoft/vscode", "monitor": "release"})

    def test_add_github_verifies_repo(self):
        source, warnings = self.add_vscode()
        self.assertEqual(source.name, "microsoft/vscode")
        self.assertEqual(warnings, [])
        self.assertIsNotNone(self.app.db.get_source(source.id))

    def test_add_unknown_repo_raises(self):
        self.transport.route(
            f"{GITHUB_API}", __import__("sentinel.errors", fromlist=["FetchHTTP"]).FetchHTTP(404)
        )
        with self.assertRaises(UsageError):
            self.app.add("github", {"repo": "microsoft/vscode"})

    def test_add_http(self):
        source, warnings = self.app.add("http", {"url": "https://example.com"})
        self.assertEqual(source.name, "example.com")
        self.assertEqual(warnings, [])

    def test_add_with_custom_name(self):
        source, _ = self.app.add("http", {"url": "https://example.com"}, name="My Website")
        self.assertEqual(source.name, "My Website")

    def test_first_check_records_baseline(self):
        self.add_vscode()
        results = self.app.check()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        self.assertTrue(results[0].first)
        self.assertEqual(results[0].changes, [])
        snap = self.app.db.latest_snapshot(results[0].source.id)
        self.assertEqual(snap.value, "1.102.0")

    def test_second_check_detects_release_change(self):
        self.add_vscode()
        self.app.check()
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {"tag_name": "1.103.0", "name": "1.103.0", "assets": []}),
        )
        results = self.app.check()
        self.assertEqual(len(results[0].changes), 1)
        change = results[0].changes[0]
        self.assertEqual(change.kind, "version")
        self.assertEqual(change.previous, "1.102.0")
        self.assertEqual(change.current, "1.103.0")
        # history now has two snapshots
        history = self.app.history("microsoft/vscode")
        self.assertEqual([s["value"] for s in history["snapshots"]], ["1.103.0", "1.102.0"])
        stored = self.app.db.list_changes(results[0].source.id)
        self.assertEqual(len(stored), 1)

    def test_failed_source_does_not_break_others(self):
        self.add_vscode()
        self.transport.route("https://example.com", make_response(200, b"hi"))
        self.app.add("http", {"url": "https://example.com"})
        self.app.check()  # baseline both

        self.transport.route("https://example.com", FetchTimeout("https://example.com", 3))
        results = self.app.check()
        by_name = {r.source.name: r for r in results}
        self.assertTrue(by_name["microsoft/vscode"].ok)
        self.assertFalse(by_name["example.com"].ok)
        self.assertIn("timeout", by_name["example.com"].error.lower())

        # availability change recorded for the failing source
        changes = self.app.db.list_changes(by_name["example.com"].source.id)
        self.assertEqual(changes[0].change.kind, "availability")
        self.assertEqual(changes[0].change.current, "offline")

    def test_recovery_recorded(self):
        self.add_vscode()
        self.transport.route("https://example.com", make_response(200, b"hi"))
        self.app.add("http", {"url": "https://example.com"})
        self.app.check()
        self.transport.route("https://example.com", FetchTimeout())
        self.app.check()
        self.transport.route("https://example.com", make_response(200, b"hi"))
        results = self.app.check()
        recovery = [c for r in results if r.source.name == "example.com" for c in r.changes]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].kind, "availability")
        self.assertEqual(recovery[0].current, "online")

    def test_resolve_by_id_name_and_prefix(self):
        self.add_vscode()
        self.assertEqual(self.app.resolve("microsoft/vscode").id, 1)
        self.assertEqual(self.app.resolve("1").id, 1)
        self.assertEqual(self.app.resolve("microsoft").id, 1)
        with self.assertRaises(UsageError):
            self.app.resolve("nope")

    def test_remove(self):
        self.add_vscode()
        removed = self.app.remove("microsoft/vscode")
        self.assertEqual(removed.name, "microsoft/vscode")
        self.assertEqual(self.app.list_sources(), [])

    def test_status_shape(self):
        self.add_vscode()
        self.app.check()
        data = self.app.status()
        self.assertEqual(len(data["sources"]), 1)
        row = data["sources"][0]
        self.assertEqual(row["value"], "1.102.0")
        self.assertEqual(row["last_status"], "ok")
        self.assertEqual(data["updates"], [])  # no updaters registered in MVP

    def test_show_shape(self):
        self.add_vscode()
        self.app.check()
        data = self.app.show("microsoft/vscode")
        self.assertEqual(data["source"].name, "microsoft/vscode")
        self.assertEqual(data["snapshot"].value, "1.102.0")

    def test_check_with_no_sources_raises(self):
        with self.assertRaises(UsageError):
            self.app.check()

    def test_self_update_graceful_when_offline(self):
        info = self.app.self_update()
        self.assertIn("current", info)
        self.assertIsNotNone(info["current"])

    def test_uptime_aggregates_checks(self):
        self.add_vscode()
        self.app.check()  # ok
        self.app.check()  # ok
        self.transport.route(f"{GITHUB_API}/releases/latest", FetchTimeout("github", 3))
        self.app.check()  # failed

        data = self.app.uptime(days=0)
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["total"], 3)
        self.assertEqual(row["ok"], 2)
        self.assertEqual(row["uptime"], 66.7)  # 2/3
        self.assertEqual(data["overall"], 66.7)
        self.assertEqual(data["total_checks"], 3)

    def test_uptime_without_checks(self):
        self.add_vscode()
        data = self.app.uptime(days=30)
        self.assertEqual(data["rows"][0]["uptime"], None)
        self.assertIsNone(data["overall"])

    def test_uptime_window_excludes_old_checks(self):
        self.add_vscode()
        sid = self.app.db.list_sources()[0].id
        # A failed check from long ago is outside the default 30-day window.
        self.app.db.record_check(sid, "2020-01-01T00:00:00Z", False, "old failure")
        self.app.check()
        data = self.app.uptime(days=30)
        self.assertEqual(data["rows"][0]["total"], 1)
        self.assertEqual(data["rows"][0]["uptime"], 100.0)


if __name__ == "__main__":
    unittest.main()

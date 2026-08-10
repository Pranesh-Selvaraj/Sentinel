import tempfile
import unittest
from pathlib import Path

from sentinel.db import Database
from sentinel.diffing import Change
from sentinel.util import utc_now


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sentinel.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()

    def test_add_and_get(self):
        sid = self.db.add_source("github", "VS Code", {"repo": "microsoft/vscode"}, utc_now())
        source = self.db.get_source(sid)
        self.assertEqual(source.name, "VS Code")
        self.assertEqual(source.kind, "github")
        self.assertEqual(source.config, {"repo": "microsoft/vscode"})
        self.assertTrue(source.enabled)
        self.assertIsNone(source.last_status)

    def test_get_unknown(self):
        self.assertIsNone(self.db.get_source(999))

    def test_list_and_enabled_filter(self):
        self.db.add_source("github", "A", {}, utc_now())
        self.db.add_source("http", "B", {}, utc_now())
        self.assertEqual(len(self.db.list_sources()), 2)
        self.assertEqual([s.name for s in self.db.list_sources(enabled_only=True)], ["A", "B"])

    def test_set_check_result(self):
        sid = self.db.add_source("http", "A", {}, utc_now())
        self.db.set_check_result(sid, True, None, utc_now())
        source = self.db.get_source(sid)
        self.assertEqual(source.last_status, "ok")
        self.db.set_check_result(sid, False, "boom", utc_now())
        source = self.db.get_source(sid)
        self.assertEqual(source.last_status, "failed")
        self.assertEqual(source.last_error, "boom")

    def test_snapshots(self):
        sid = self.db.add_source("github", "A", {}, utc_now())
        self.db.record_snapshot(sid, "2026-08-01T00:00:00Z", "1.0.0", {"tag": "v1.0.0"}, None)
        self.db.record_snapshot(sid, "2026-08-02T00:00:00Z", "1.0.1", {"tag": "v1.0.1"}, None)
        latest = self.db.latest_snapshot(sid)
        self.assertEqual(latest.value, "1.0.1")
        snaps = self.db.list_snapshots(sid)
        self.assertEqual([s.value for s in snaps], ["1.0.1", "1.0.0"])

    def test_changes(self):
        sid = self.db.add_source("github", "A", {}, utc_now())
        self.db.record_changes(sid, utc_now(), [Change("version", "1.0.0", "1.0.1", "New release detected")])
        stored = self.db.list_changes(sid)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].change.kind, "version")
        self.assertEqual(stored[0].change.current, "1.0.1")
        self.assertEqual(self.db.latest_change(sid).change.description, "New release detected")

    def test_checks_log(self):
        sid = self.db.add_source("http", "A", {}, utc_now())
        self.db.record_check(sid, utc_now(), True, None)
        self.db.record_check(sid, utc_now(), False, "timeout")
        rows = self.db.conn.execute("SELECT ok FROM checks WHERE source_id = ?", (sid,)).fetchall()
        self.assertEqual([r["ok"] for r in rows], [1, 0])

    def test_delete_cascades(self):
        sid = self.db.add_source("http", "A", {}, utc_now())
        self.db.record_snapshot(sid, utc_now(), "200", {"status": 200}, None)
        self.db.record_changes(sid, utc_now(), [Change("status", "200", "404")])
        self.db.delete_source(sid)
        self.assertIsNone(self.db.latest_snapshot(sid))
        self.assertEqual(self.db.list_changes(sid), [])

    def test_persistence_across_reopen(self):
        sid = self.db.add_source("github", "Persist", {"repo": "a/b"}, utc_now())
        self.db.record_snapshot(sid, utc_now(), "1.0.0", {}, None)
        self.db.close()
        reopened = Database(self.path)
        try:
            sources = reopened.list_sources()
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].name, "Persist")
            self.assertEqual(reopened.latest_snapshot(sid).value, "1.0.0")
        finally:
            reopened.close()
        self.db = Database(self.path)  # keep tearDown working

    def test_updates_audit(self):
        sid = self.db.add_source("github", "A", {}, utc_now())
        self.db.record_update(sid, "VS Code", "1.100.0", "1.101.0", "https://code.visualstudio.com", utc_now(), "pending")
        rows = self.db.list_updates()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_version"], "1.101.0")


if __name__ == "__main__":
    unittest.main()

import hashlib
import tempfile
import unittest
from pathlib import Path

from sentinel.app import SentinelApp
from sentinel.errors import FetchTimeout
from sentinel.models import Source
from sentinel.update import UpgradeService
from sentinel.updaters.github_release import GitHubReleaseUpdater
from tests.fakes import FakeTransport, make_json_response, make_response

GITHUB_API = "https://api.github.com/repos/acme/tool"


class GitHubReleaseUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.install_path = Path(self.tmp.name) / "tools" / "tool"
        self.updater = GitHubReleaseUpdater()
        self.transport = FakeTransport()

        self.asset = {"name": "tool-linux-x64.tar.gz", "size": 1024,
                      "browser_download_url": "https://downloads.acme/tool-linux-x64.tar.gz"}
        self.release = {"tag_name": "1.103.0", "name": "1.103.0", "assets": [self.asset]}

    def src(self, **overrides) -> Source:
        config = {"repo": "acme/tool", "monitor": "release", "install_path": str(self.install_path)}
        config.update(overrides)
        return Source(id=1, kind="github", name="tool", config=config)

    def route_release(self, release: dict | None = None) -> None:
        self.transport.route(
            f"{GITHUB_API}/releases/latest", make_json_response(200, release or self.release)
        )

    def route_asset(self, data: bytes = b"artifact-bytes") -> None:
        self.transport.route(self.asset["browser_download_url"], make_response(200, data))

    def route_sha256(self, data: bytes) -> None:
        """Attach a sibling ``<asset>.sha256`` checksum file to the release."""
        digest = hashlib.sha256(data).hexdigest()
        name = "tool-linux-x64.tar.gz.sha256"
        url = "https://downloads.acme/tool-linux-x64.tar.gz.sha256"
        self.release["assets"].append({"name": name, "size": 64, "browser_download_url": url})
        self.transport.route(url, make_response(200, digest))
        self.route_release()  # re-route with the updated asset list

    # -- planning ---------------------------------------------------------
    def test_plan_verified_with_sibling_checksum(self):
        self.route_release()
        self.route_sha256(b"artifact-bytes")
        plan = self.updater.plan(self.src(), self.transport)
        self.assertIsNotNone(plan)
        self.assertFalse(plan.noop)
        self.assertEqual(plan.latest_version, "1.103.0")
        self.assertIsNone(plan.installed_version)
        self.assertTrue(plan.verified)
        self.assertEqual([a.name for a in plan.assets], ["tool-linux-x64.tar.gz"])
        self.assertEqual(plan.checksums["tool-linux-x64.tar.gz"]["algo"], "sha256")

    def test_plan_verified_via_sumfile(self):
        asset2 = {"name": "tool-linux-arm64.tar.gz", "size": 512,
                  "browser_download_url": "https://downloads.acme/tool-linux-arm64.tar.gz"}
        digest = hashlib.sha256(b"artifact-bytes").hexdigest()
        self.release["assets"] = [self.asset, asset2, {
            "name": "SHA256SUMS", "size": 128,
            "browser_download_url": "https://downloads.acme/SHA256SUMS",
        }]
        self.route_release()
        self.transport.route(
            "https://downloads.acme/SHA256SUMS",
            make_response(200, f"{digest}  tool-linux-x64.tar.gz\n"),
        )
        # default selection picks the largest asset
        plan = self.updater.plan(self.src(), self.transport)
        self.assertEqual([a.name for a in plan.assets], ["tool-linux-x64.tar.gz"])
        self.assertTrue(plan.verified)

    def test_plan_verified_via_jq_style_sumfile(self):
        """jq names its manifest `sha256sum.txt` (singular) — must be found."""
        digest = hashlib.sha256(b"artifact-bytes").hexdigest()
        self.release["assets"].append({
            "name": "sha256sum.txt", "size": 128,
            "browser_download_url": "https://downloads.acme/sha256sum.txt",
        })
        self.route_release()
        self.transport.route(
            "https://downloads.acme/sha256sum.txt",
            make_response(200, f"{digest} *tool-linux-x64.tar.gz\n"),
        )
        plan = self.updater.plan(self.src(), self.transport)
        self.assertTrue(plan.verified)
        self.assertEqual(plan.checksums["tool-linux-x64.tar.gz"]["algo"], "sha256")

    def test_plan_picks_largest_asset_without_pattern(self):
        small = {"name": "tool-docs.zip", "size": 10, "browser_download_url": "https://d/small.zip"}
        self.route_release({"tag_name": "1.103.0", "name": "1.103.0", "assets": [small, self.asset]})
        plan = self.updater.plan(self.src(), self.transport)
        self.assertEqual([a.name for a in plan.assets], ["tool-linux-x64.tar.gz"])

    def test_plan_asset_pattern(self):
        small = {"name": "tool-docs.zip", "size": 10, "browser_download_url": "https://d/small.zip"}
        self.route_release({"tag_name": "1.103.0", "name": "1.103.0", "assets": [small, self.asset]})
        plan = self.updater.plan(self.src(assets=["*.zip"]), self.transport)
        self.assertEqual([a.name for a in plan.assets], ["tool-docs.zip"])

    def test_plan_up_to_date_is_noop(self):
        self.install_path.mkdir(parents=True)
        (self.install_path / ".sentinel-version").write_text("1.103.0\n")
        self.route_release()
        plan = self.updater.plan(self.src(), self.transport)
        self.assertTrue(plan.noop)
        self.assertIn("already up to date", plan.noop_reason)

    def test_plan_no_install_path_returns_none(self):
        self.route_release()
        plan = self.updater.plan(Source(id=1, kind="github", name="tool",
                                        config={"repo": "acme/tool", "monitor": "release"}), self.transport)
        self.assertIsNone(plan)

    def test_plan_no_assets_is_noop(self):
        self.route_release({"tag_name": "1.103.0", "name": "1.103.0", "assets": []})
        plan = self.updater.plan(self.src(), self.transport)
        self.assertTrue(plan.noop)
        self.assertIn("no downloadable assets", plan.noop_reason)

    def test_plan_tags_monitor_is_noop(self):
        plan = self.updater.plan(self.src(monitor="tags"), self.transport)
        self.assertTrue(plan.noop)

    def test_plan_unverified_without_checksum(self):
        self.route_release()
        self.route_asset()
        plan = self.updater.plan(self.src(), self.transport)
        self.assertFalse(plan.verified)
        self.assertIn("--allow-unverified", plan.verify_note)

    # -- applying ---------------------------------------------------------
    def test_apply_downloads_verifies_and_marks(self):
        self.route_release()
        self.route_asset(b"artifact-bytes")
        self.route_sha256(b"artifact-bytes")
        plan = self.updater.plan(self.src(), self.transport)
        result = self.updater.apply(plan, self.transport)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "downloaded")
        self.assertTrue(result.verified)
        target = self.install_path / "1.103.0" / "tool-linux-x64.tar.gz"
        self.assertEqual(target.read_bytes(), b"artifact-bytes")
        self.assertEqual((self.install_path / ".sentinel-version").read_text().strip(), "1.103.0")

    def test_apply_blocks_unverified(self):
        self.route_release()
        self.route_asset()
        plan = self.updater.plan(self.src(), self.transport)
        result = self.updater.apply(plan, self.transport)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("--allow-unverified", result.message)
        self.assertFalse((self.install_path / "1.103.0").exists())

    def test_apply_allow_unverified_flag(self):
        self.route_release()
        self.route_asset(b"artifact-bytes")
        plan = self.updater.plan(self.src(), self.transport)
        result = self.updater.apply(plan, self.transport, allow_unverified=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "downloaded-unverified")
        self.assertTrue((self.install_path / "1.103.0" / "tool-linux-x64.tar.gz").exists())

    def test_apply_checksum_mismatch_discards(self):
        self.route_release()
        self.route_asset(b"artifact-bytes")
        self.route_sha256(b"different-bytes")
        plan = self.updater.plan(self.src(), self.transport)
        result = self.updater.apply(plan, self.transport)
        self.assertFalse(result.ok)
        self.assertIn("checksum mismatch", result.message)
        self.assertFalse((self.install_path / "1.103.0").exists())


class UpgradeServiceTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()

    def src(self, kind: str, name: str, config: dict) -> Source:
        return Source(id=1, kind=kind, name=name, config=config)

    def test_http_source_skipped_monitoring_only(self):
        report = UpgradeService(self.transport).plan_all(
            [self.src("http", "example.com", {"url": "https://example.com"})]
        )
        self.assertEqual(report.plans, [])
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("monitoring only", report.skipped[0]["reason"])

    def test_github_without_install_path_skipped(self):
        report = UpgradeService(self.transport).plan_all(
            [self.src("github", "tool", {"repo": "a/b", "monitor": "release"})]
        )
        self.assertIn("--install-path", report.skipped[0]["reason"])

    def test_fetch_failure_skipped_not_crash(self):
        transport = FakeTransport({
            f"{GITHUB_API}/releases/latest": FetchTimeout("github", 3),
        })
        report = UpgradeService(transport).plan_all(
            [self.src("github", "tool", {"repo": "acme/tool", "monitor": "release",
                                         "install_path": "/tmp/x"})]
        )
        self.assertEqual(report.plans, [])
        self.assertIn("could not check", report.skipped[0]["reason"])


class AppUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.install_path = Path(self.tmp.name) / "tools" / "tool"
        self.transport = FakeTransport()
        self.app = SentinelApp(config_dir=self.dir, transport=self.transport)

    def tearDown(self):
        self.app.close()

    def add_updatable_source(self, name: str = "tool") -> None:
        digest = hashlib.sha256(b"payload").hexdigest()
        self.transport.route(GITHUB_API, make_json_response(200, {"full_name": "acme/tool"}))
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {
                "tag_name": "1.103.0", "name": "1.103.0",
                "assets": [
                    {"name": "tool.tar.gz", "size": 10,
                     "browser_download_url": "https://downloads.acme/tool.tar.gz"},
                    {"name": "tool.tar.gz.sha256", "size": 64,
                     "browser_download_url": "https://downloads.acme/tool.tar.gz.sha256"},
                ],
            }),
        )
        self.transport.route("https://downloads.acme/tool.tar.gz", make_response(200, b"payload"))
        self.transport.route("https://downloads.acme/tool.tar.gz.sha256", make_response(200, digest))
        self.app.add("github", {"repo": "acme/tool", "monitor": "release",
                                "install_path": str(self.install_path)}, name=name)

    def test_upgrade_plans_and_apply_records_audit(self):
        self.add_updatable_source()
        report = self.app.upgrade(["tool"])
        self.assertEqual(len(report.plans), 1)
        result = self.app.apply_update(report.plans[0])
        self.assertTrue(result.ok)
        self.assertTrue((self.install_path / "1.103.0" / "tool.tar.gz").exists())
        audit = self.app.db.list_updates()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["status"], "downloaded")
        self.assertEqual(audit[0]["latest_version"], "1.103.0")

    def test_upgrade_selection_by_ref(self):
        self.add_updatable_source()
        self.app.add("http", {"url": "https://example.com"})
        report = self.app.upgrade(["tool"])
        self.assertEqual(len(report.plans), 1)
        self.assertEqual(report.plans[0].tool, "tool")

    def test_upgrade_unknown_ref_raises(self):
        with self.assertRaises(Exception):
            self.app.upgrade(["nope"])


if __name__ == "__main__":
    unittest.main()

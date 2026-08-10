import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sentinel.cli
from sentinel.app import SentinelApp
from sentinel.errors import FetchTimeout
from tests.fakes import FakeTransport, make_json_response, make_response

GITHUB_API = "https://api.github.com/repos/microsoft/vscode"


class CliTestCase(unittest.TestCase):
    """Runs the real CLI with a fake transport and an isolated config dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.transport = FakeTransport()
        self.stdout = io.StringIO()

        def factory(config_dir=None):
            return SentinelApp(config_dir=config_dir, transport=self.transport)

        patcher = mock.patch.object(sentinel.cli, "create_app", side_effect=factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str) -> int:
        with contextlib.redirect_stdout(self.stdout):
            return sentinel.cli.main(list(argv))

    def add_vscode(self):
        self.transport.route(f"{GITHUB_API}", make_json_response(200, {"full_name": "microsoft/vscode"}))
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {"tag_name": "1.102.0", "name": "1.102.0", "assets": []}),
        )
        return self.run_cli("add", "github", "microsoft/vscode", "--monitor", "release", "--config-dir", str(self.dir))

    def test_no_arguments_shows_help(self):
        code = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("add", self.stdout.getvalue())

    def test_add_list_check_status_history_flow(self):
        self.assertEqual(self.add_vscode(), 0)
        self.assertIn("Added microsoft/vscode", self.stdout.getvalue())
        self.assertIn("Monitoring: release", self.stdout.getvalue())

        # list
        self.stdout.seek(0)
        self.stdout.truncate()
        self.assertEqual(self.run_cli("list", "--config-dir", str(self.dir)), 0)
        listed = self.stdout.getvalue()
        self.assertIn("microsoft/vscode", listed)
        self.assertIn("GitHub", listed)
        self.assertIn("release", listed)

        # first check: baseline, exit 0
        self.assertEqual(self.run_cli("check", "--config-dir", str(self.dir)), 0)

        # a new release appears -> check exits 1
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {"tag_name": "1.103.0", "name": "1.103.0", "assets": []}),
        )
        code = self.run_cli("check", "--config-dir", str(self.dir))
        self.assertEqual(code, 1)
        output = self.stdout.getvalue()
        self.assertIn("1.102.0 → 1.103.0", output)
        self.assertIn("New release detected", output)
        self.assertIn("1 change detected", output)

        # status
        self.assertEqual(self.run_cli("status", "--config-dir", str(self.dir)), 0)
        self.assertIn("1.103.0", self.stdout.getvalue())

        # history
        self.assertEqual(self.run_cli("history", "microsoft", "--config-dir", str(self.dir)), 0)
        history = self.stdout.getvalue()
        self.assertIn("History", history)
        self.assertIn("1.103.0", history)
        self.assertIn("1.102.0", history)

    def test_json_output(self):
        self.add_vscode()
        self.run_cli("check", "--config-dir", str(self.dir))
        self.stdout.seek(0)
        self.stdout.truncate()
        self.assertEqual(self.run_cli("list", "--json", "--config-dir", str(self.dir)), 0)
        import json

        payload = json.loads(self.stdout.getvalue())
        self.assertEqual(payload[0]["name"], "microsoft/vscode")
        self.assertEqual(payload[0]["kind"], "github")

    def test_check_failure_exit_code(self):
        self.add_vscode()
        self.transport.route(
            f"{GITHUB_API}/releases/latest", FetchTimeout("github", 3)
        )
        code = self.run_cli("check", "--config-dir", str(self.dir))
        self.assertEqual(code, 2)
        self.assertIn("timeout", self.stdout.getvalue().lower())

    def test_check_exit_zero_flag(self):
        self.add_vscode()
        self.transport.route(
            f"{GITHUB_API}/releases/latest", FetchTimeout("github", 3)
        )
        code = self.run_cli("check", "--exit-zero", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)

    def test_remove_requires_yes_noninteractive(self):
        self.add_vscode()
        code = self.run_cli("remove", "microsoft/vscode", "--config-dir", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("--yes", self.stdout.getvalue())
        self.assertEqual(self.run_cli("remove", "microsoft/vscode", "--yes", "--config-dir", str(self.dir)), 0)
        self.assertIn("Removed", self.stdout.getvalue())

    def test_unknown_source_error(self):
        self.add_vscode()
        code = self.run_cli("show", "nope", "--config-dir", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("unknown source", self.stdout.getvalue())

    def test_config_path(self):
        code = self.run_cli("config", "--path", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        self.assertEqual(self.stdout.getvalue().strip(), str(self.dir))

    def test_upgrade_skips_sources_without_install_path(self):
        self.add_vscode()
        code = self.run_cli("upgrade", "--dry-run", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        output = self.stdout.getvalue()
        self.assertIn("--install-path", output)
        self.assertIn("Nothing to update.", output)

    # -- upgrade with install path ----------------------------------------
    def add_updatable_vscode(self) -> str:
        """Add vscode with an install path and a checksummed release asset."""
        import hashlib

        install_path = Path(self.tmp.name) / "tools" / "vscode"
        digest = hashlib.sha256(b"release-bytes").hexdigest()
        self.transport.route(f"{GITHUB_API}", make_json_response(200, {"full_name": "microsoft/vscode"}))
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {
                "tag_name": "1.103.0", "name": "1.103.0",
                "assets": [
                    {"name": "code.tar.gz", "size": 1000,
                     "browser_download_url": "https://downloads.acme/code.tar.gz"},
                    {"name": "code.tar.gz.sha256", "size": 64,
                     "browser_download_url": "https://downloads.acme/code.tar.gz.sha256"},
                ],
            }),
        )
        self.transport.route("https://downloads.acme/code.tar.gz", make_response(200, b"release-bytes"))
        self.transport.route("https://downloads.acme/code.tar.gz.sha256", make_response(200, digest))
        self.run_cli("add", "github", "microsoft/vscode", "--monitor", "release",
                     "--install-path", str(install_path), "--config-dir", str(self.dir))
        return str(install_path)

    def test_upgrade_dry_run_shows_plan(self):
        self.add_updatable_vscode()
        code = self.run_cli("upgrade", "--dry-run", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        output = self.stdout.getvalue()
        self.assertIn("not downloaded", output)
        self.assertIn("1.103.0", output)
        self.assertIn("checksum verified", output)
        self.assertIn("--dry-run", output)

    def test_upgrade_applies_with_yes(self):
        install_path = self.add_updatable_vscode()
        code = self.run_cli("upgrade", "--yes", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        output = self.stdout.getvalue()
        self.assertIn("downloaded 1.103.0", output)
        self.assertIn("1 update applied", output)
        target = Path(install_path) / "1.103.0" / "code.tar.gz"
        self.assertEqual(target.read_bytes(), b"release-bytes")
        self.assertEqual((Path(install_path) / ".sentinel-version").read_text().strip(), "1.103.0")

    def test_upgrade_requires_yes_noninteractive(self):
        self.add_updatable_vscode()
        code = self.run_cli("upgrade", "--config-dir", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("--yes", self.stdout.getvalue())

    def test_upgrade_selected_sources_only(self):
        self.add_updatable_vscode()
        self.transport.route("https://example.com", make_response(200, b"hi"))
        self.run_cli("add", "http", "https://example.com", "--name", "Website", "--config-dir", str(self.dir))
        self.stdout.seek(0)
        self.stdout.truncate()
        code = self.run_cli("upgrade", "--yes", "microsoft/vscode", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("downloaded 1.103.0", self.stdout.getvalue())
        # The http source was never part of the run.
        self.assertNotIn("Website", self.stdout.getvalue())

    def test_upgrade_unverified_blocked(self):
        install_path = Path(self.tmp.name) / "tools" / "vscode"
        self.transport.route(f"{GITHUB_API}", make_json_response(200, {"full_name": "microsoft/vscode"}))
        self.transport.route(
            f"{GITHUB_API}/releases/latest",
            make_json_response(200, {
                "tag_name": "1.103.0", "name": "1.103.0",
                "assets": [{"name": "code.tar.gz", "size": 1000,
                             "browser_download_url": "https://downloads.acme/code.tar.gz"}],
            }),
        )
        self.transport.route("https://downloads.acme/code.tar.gz", make_response(200, b"release-bytes"))
        self.run_cli("add", "github", "microsoft/vscode", "--monitor", "release",
                     "--install-path", str(install_path), "--config-dir", str(self.dir))
        self.stdout.seek(0)
        self.stdout.truncate()
        code = self.run_cli("upgrade", "--yes", "--config-dir", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("--allow-unverified", self.stdout.getvalue())
        self.assertFalse((install_path / "1.103.0").exists())

    def test_add_http(self):
        self.transport.route("https://example.com", make_response(200, b"<title>Example</title>"))
        code = self.run_cli("add", "http", "https://example.com", "--name", "Example", "--config-dir", str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("Added Example", self.stdout.getvalue())

    def test_add_api_with_headers(self):
        code = self.run_cli(
            "add", "api", "https://api.example.com/version", "--jpath", "$.version",
            "--header", "X-Api-Key=${API_KEY}", "--config-dir", str(self.dir),
        )
        self.assertEqual(code, 0)
        self.assertIn("Added api.example.com", self.stdout.getvalue())

    def test_unknown_command(self):
        self.assertEqual(self.run_cli("frobnicate"), 2)


if __name__ == "__main__":
    unittest.main()

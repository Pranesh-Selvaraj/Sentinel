import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sentinel.config import default_config_dir, load_settings
from sentinel.errors import ConfigError


class ConfigDirTests(unittest.TestCase):
    def test_env_override(self):
        with mock.patch.dict(os.environ, {"SENTINEL_HOME": "/tmp/x"}, clear=False):
            self.assertEqual(default_config_dir(), Path("/tmp/x"))

    def test_linux_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("sentinel.config.sys.platform", "linux"):
                with mock.patch("sentinel.config.os.name", "posix"):
                    self.assertEqual(default_config_dir(), Path.home() / ".sentinel")


class LoadSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write_config(self, content: str) -> Path:
        path = self.dir / "config.toml"
        path.write_text(content)
        return path

    def test_defaults_without_file(self):
        settings = load_settings(self.dir)
        self.assertEqual(settings.timeout, 30.0)
        self.assertEqual(settings.retries, 3)
        self.assertEqual(settings.check_interval, "1h")
        self.assertEqual(settings.db_path, self.dir / "sentinel.db")
        self.assertIsNone(settings.github_token)

    def test_loads_toml(self):
        self.write_config(
            "[sentinel]\n"
            'check_interval = "10m"\n'
            "timeout = 5\n"
            "retries = 1\n"
            "\n"
            "[github]\n"
            'token = "ghp_file_token"\n'
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            settings = load_settings(self.dir)
        self.assertEqual(settings.check_interval, "10m")
        self.assertEqual(settings.timeout, 5.0)
        self.assertEqual(settings.retries, 1)
        self.assertEqual(settings.github_token, "ghp_file_token")

    def test_env_token_overrides_file(self):
        self.write_config('[github]\ntoken = "ghp_file_token"\n')
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_env_token"}, clear=False):
            settings = load_settings(self.dir)
        self.assertEqual(settings.github_token, "ghp_env_token")

    def test_invalid_toml(self):
        self.write_config("not [ valid toml")
        with self.assertRaises(ConfigError):
            load_settings(self.dir)

    def test_invalid_interval(self):
        self.write_config('[sentinel]\ncheck_interval = "soon"\n')
        with self.assertRaises(ConfigError):
            load_settings(self.dir)

    def test_invalid_timeout(self):
        self.write_config("[sentinel]\ntimeout = -1\n")
        with self.assertRaises(ConfigError):
            load_settings(self.dir)


if __name__ == "__main__":
    unittest.main()

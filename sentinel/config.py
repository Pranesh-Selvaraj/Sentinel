"""Configuration: config directory resolution and ``config.toml`` loading.

Layout (platform-aware):

    Linux:   ~/.sentinel/config.toml + sentinel.db
    macOS:   ~/Library/Application Support/Sentinel/
    Windows: %APPDATA%\\Sentinel\\

``SENTINEL_HOME`` overrides the config directory anywhere. ``GITHUB_TOKEN``
(when set) overrides ``[github] token`` in the config file. Secrets should
prefer environment variables over the config file.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sentinel import __version__
from sentinel.errors import ConfigError
from sentinel.util import parse_interval

APP_DIR_NAME = "Sentinel"  # macOS / Windows
LINUX_DIR_NAME = ".sentinel"


def default_config_dir() -> Path:
    """Platform-appropriate config directory (``SENTINEL_HOME`` wins)."""
    env = os.environ.get("SENTINEL_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home())
        return base / APP_DIR_NAME
    return Path.home() / LINUX_DIR_NAME


@dataclass
class Settings:
    """Resolved runtime settings."""

    config_dir: Path
    timeout: float = 30.0
    retries: int = 3
    check_interval: str = "1h"
    user_agent: str = f"sentinel/{__version__}"
    github_token: str | None = None
    _raw: dict = field(default_factory=dict, repr=False)

    @property
    def db_path(self) -> Path:
        return self.config_dir / "sentinel.db"

    def to_dict(self) -> dict:
        return {
            "config_dir": str(self.config_dir),
            "db_path": str(self.db_path),
            "timeout": self.timeout,
            "retries": self.retries,
            "check_interval": self.check_interval,
            "user_agent": self.user_agent,
            "github_token": "***" if self.github_token else None,
        }


def load_settings(config_dir: str | Path | None = None) -> Settings:
    """Load settings, merging ``config.toml`` over platform defaults."""
    directory = Path(config_dir).expanduser() if config_dir else default_config_dir()
    raw: dict = {}
    config_file = directory / "config.toml"
    if config_file.exists():
        try:
            with open(config_file, "rb") as fh:
                raw = tomllib.load(fh)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"invalid config file {config_file}: {exc}") from exc

    sentinel_cfg = raw.get("sentinel", {})
    http_cfg = raw.get("http", {})
    github_cfg = raw.get("github", {})

    timeout = float(sentinel_cfg.get("timeout", 30.0))
    retries = int(sentinel_cfg.get("retries", 3))
    interval = str(sentinel_cfg.get("check_interval", "1h"))
    try:
        parse_interval(interval)
    except ValueError as exc:
        raise ConfigError(f"invalid check_interval in {config_file}: {exc}") from exc
    if timeout <= 0:
        raise ConfigError("timeout must be positive")
    if retries < 0:
        raise ConfigError("retries must be >= 0")

    token = os.environ.get("GITHUB_TOKEN") or github_cfg.get("token") or None
    user_agent = str(http_cfg.get("user_agent", f"sentinel/{__version__}"))

    return Settings(
        config_dir=directory,
        timeout=timeout,
        retries=retries,
        check_interval=interval,
        user_agent=user_agent,
        github_token=token or None,
        _raw=raw,
    )

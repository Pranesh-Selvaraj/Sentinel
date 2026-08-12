"""npm package monitor: the latest release of an npm package.

Data comes from the official npm registry (``registry.npmjs.org/<name>``).
Monitoring only — package registries are read-only sources, like websites
and APIs. (Updaters that download tarballs are future work.)
"""

from __future__ import annotations

import re

from sentinel.diffing import Change, ChangeDetector
from sentinel.errors import ConfigError, FetchInvalidJSON
from sentinel.httpclient import Transport
from sentinel.models import Observation, Source
from sentinel.monitors import _registry
from sentinel.monitors.base import Monitor
from sentinel.term import input_text
from sentinel.util import json_dumps_compact, truncate

API = "https://registry.npmjs.org/{name}"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")


class NpmMonitor(Monitor):
    kind = "npm"
    label = "npm package"

    @classmethod
    def default_name(cls, config: dict) -> str:
        return config.get("name", "npm")

    @classmethod
    def prompt(cls) -> dict:
        while True:
            name = input_text("Package name (e.g. express)")
            if NAME_RE.match(name or ""):
                return {"name": name.strip(), "monitor": "release"}
            print("Expected a valid npm package name (letters, digits, . _ ~ -)")

    def fetch(self, source: Source, transport: Transport) -> Observation:
        name = source.config.get("name", "").strip()
        if not name or not NAME_RE.match(name):
            raise ConfigError(f"invalid npm package name {name!r}")
        data = transport.get_json(API.format(name=name))
        if not isinstance(data, dict):
            raise FetchInvalidJSON(API.format(name=name))
        dist_tags = data.get("dist-tags") or {}
        version = dist_tags.get("latest")
        modified = data.get("modified")
        state = {
            "monitor": "release",
            "version": version,
            "name": data.get("name") or name,
            "modified": modified,
            "description": (data.get("description") or "")[:200],
            "homepage": data.get("homepage"),
        }
        raw = truncate(
            json_dumps_compact(
                {
                    "name": state["name"],
                    "version": version,
                    "modified": modified,
                    "description": state["description"],
                }
            ),
            4096,
        )
        return Observation(value=str(version) if version is not None else None, state=state, raw=raw)

    def diff(self, source: Source, previous: Observation | None, current: Observation) -> list[Change]:
        if previous is None:
            return []
        change = ChangeDetector.version(previous.value, current.value, label="release")
        return [change] if change else []

    def format_value(self, source: Source, value: str | None) -> str:
        return value if value is not None else "—"


_registry.register(NpmMonitor)

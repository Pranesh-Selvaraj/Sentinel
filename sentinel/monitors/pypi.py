"""PyPI package monitor: the latest release of a Python package.

Data comes from the official PyPI JSON API (``pypi.org/pypi/<name>/json``).
Monitoring only — like websites and APIs, package registries are read-only
sources. (Updaters that download wheels/sdists are future work; see
``sentinel/updaters/``.)
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

API = "https://pypi.org/pypi/{name}/json"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PyPIMonitor(Monitor):
    kind = "pypi"
    label = "PyPI package"

    @classmethod
    def default_name(cls, config: dict) -> str:
        return config.get("name", "pypi")

    @classmethod
    def prompt(cls) -> dict:
        while True:
            name = input_text("Package name (e.g. requests)")
            if NAME_RE.match(name or ""):
                return {"name": name.strip(), "monitor": "release"}
            print("Expected a valid PyPI package name (letters, digits, . _ -)")

    def fetch(self, source: Source, transport: Transport) -> Observation:
        name = source.config.get("name", "").strip()
        if not name or not NAME_RE.match(name):
            raise ConfigError(f"invalid PyPI package name {name!r}")
        try:
            data = transport.get_json(API.format(name=name))
        except FetchInvalidJSON:
            raise  # pypi.org returns JSON; a non-JSON body means a proxy/edge problem
        if not isinstance(data, dict):
            raise FetchInvalidJSON(API.format(name=name))
        info = data.get("info") or {}
        version = info.get("version")
        released = None
        for upload in data.get("urls") or []:
            released = upload.get("upload_time_iso_8601") or upload.get("upload_time")
            if released:
                break
        state = {
            "monitor": "release",
            "version": version,
            "name": info.get("name") or name,
            "released": released,
            "summary": (info.get("summary") or "")[:200],
            "project_url": info.get("project_urls") or {},
        }
        raw = truncate(
            json_dumps_compact(
                {"name": state["name"], "version": version, "released": released, "summary": state["summary"]}
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


_registry.register(PyPIMonitor)

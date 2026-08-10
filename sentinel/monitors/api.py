"""API endpoint monitor: GET + status + JSON body + JSON field extraction.

Example config::

    {"url": "https://api.example.com/version", "jpath": "$.version"}

``jpath`` supports ``$.a.b``, ``$.a[0].b`` and bare ``a.b``. Header values may
reference environment variables with ``${VAR}`` so API keys never need to be
stored in the database.
"""

from __future__ import annotations

import json
import os
import re

from sentinel.diffing import Change, ChangeDetector
from sentinel.errors import FetchInvalidJSON
from sentinel.models import Observation, Source
from sentinel.monitors import _registry
from sentinel.monitors.base import Monitor
from sentinel.term import input_text
from sentinel.util import json_dumps_compact, resolve_jpath, sha256_hex, truncate

_ENV_REF = re.compile(r"\$\{(\w+)\}")
RAW_PREVIEW = 4096


def _expand_env(value: str) -> str:
    """Expand ``${VAR}`` references from the environment (left literal when unset)."""
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _stringify(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = json_dumps_compact(value)
        return text if len(text) <= 200 else text[:197] + "..."
    return str(value)


class ApiMonitor(Monitor):
    kind = "api"
    label = "API endpoint"

    @classmethod
    def default_name(cls, config: dict) -> str:
        from urllib.parse import urlparse

        host = urlparse(config.get("url", "")).hostname or config.get("url", "")
        return host

    @classmethod
    def prompt(cls) -> dict:
        while True:
            url = input_text("URL (https://…)")
            if url.startswith(("http://", "https://")):
                break
            print("URL must start with http:// or https://")
        jpath = input_text("JSON path (optional)", default="$.version")
        config = {"url": url}
        if jpath:
            config["jpath"] = jpath
        return config

    def fetch(self, source: Source, transport: Transport) -> Observation:
        config = source.config
        url = config["url"]
        headers = {k: _expand_env(str(v)) for k, v in (config.get("headers") or {}).items()}
        resp = transport.get(url, headers or None)

        try:
            data = json.loads(resp.body.decode("utf-8", "replace"))
        except (ValueError, UnicodeDecodeError):
            raise FetchInvalidJSON(url)

        jpath = config.get("jpath")
        if jpath:
            try:
                extracted = resolve_jpath(data, jpath)
            except KeyError:
                extracted = None
            state = {
                "status": resp.status,
                "jpath": jpath,
                "value": _stringify(extracted),
            }
            value = state["value"]
        else:
            digest = sha256_hex(resp.body)
            state = {"status": resp.status, "body_sha256": digest}
            value = str(resp.status)

        raw = truncate(resp.body.decode("utf-8", "replace"), RAW_PREVIEW)
        return Observation(value=value, state=state, raw=raw)

    def diff(self, source: Source, previous: Observation | None, current: Observation) -> list[Change]:
        if previous is None:
            return []
        status_change = ChangeDetector.status(
            previous.state.get("status"), current.state.get("status")
        )
        if status_change:
            return [status_change]

        jpath = source.config.get("jpath")
        if jpath:
            change = ChangeDetector.json_field(
                jpath, previous.state.get("value"), current.state.get("value")
            )
            return [change] if change else []

        body_change = ChangeDetector.content(
            previous.state.get("body_sha256"),
            current.state.get("body_sha256"),
            description="Response body changed",
        )
        return [body_change] if body_change else []

    def format_value(self, source: Source, value: str | None) -> str:
        if value is None:
            return "—"
        if source.config.get("jpath"):
            return value
        return f"HTTP {value}"


_registry.register(ApiMonitor)

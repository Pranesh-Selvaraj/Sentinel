"""HTTP/website monitor: status code + content fingerprint."""

from __future__ import annotations

import json
import re

from sentinel.diffing import Change, ChangeDetector
from sentinel.models import Observation, Source
from sentinel.monitors.base import Monitor
from sentinel.monitors import _registry
from sentinel.term import input_text
from sentinel.util import sha256_hex, truncate

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
MAX_BODY = 256 * 1024  # fingerprint at most this much of the body
RAW_PREVIEW = 4096


class HttpMonitor(Monitor):
    kind = "http"
    label = "Website"

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
                return {"url": url}
            print("URL must start with http:// or https://")

    def fetch(self, source: Source, transport: Transport) -> Observation:
        url = source.config["url"]
        resp = transport.get(url)
        body = resp.body[:MAX_BODY]
        title_match = TITLE_RE.search(body.decode("utf-8", "replace"))
        title = title_match.group(1).strip()[:200] if title_match else None
        digest = sha256_hex(body)
        state = {
            "status": resp.status,
            "content_sha256": digest,
            "content_length": len(body),
            "content_type": resp.headers.get("content-type"),
            "title": title,
            "final_url": resp.url,
        }
        raw = truncate(body.decode("utf-8", "replace"), RAW_PREVIEW)
        return Observation(value=str(resp.status), state=state, raw=raw)

    def diff(self, source: Source, previous: Observation | None, current: Observation) -> list[Change]:
        if previous is None:
            return []
        status_change = ChangeDetector.status(
            previous.state.get("status"), current.state.get("status")
        )
        if status_change:
            return [status_change]  # status moved; content details are moot
        content_change = ChangeDetector.content(
            previous.state.get("content_sha256"), current.state.get("content_sha256")
        )
        return [content_change] if content_change else []

    def format_value(self, source: Source, value: str | None) -> str:
        return f"HTTP {value}" if value is not None else "—"


_registry.register(HttpMonitor)

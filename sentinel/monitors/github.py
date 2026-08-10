"""GitHub monitor: repository releases, tags and commits.

Data comes from the official GitHub REST API. Authentication is optional via
``GITHUB_TOKEN`` (env var) or ``[github] token`` in ``config.toml``; the
token is never stored in the database and never printed.
"""

from __future__ import annotations

import json
import os

from sentinel.diffing import Change, ChangeDetector
from sentinel.errors import ConfigError, FetchHTTP
from sentinel.httpclient import Transport
from sentinel.models import Observation, Source
from sentinel.monitors.base import Monitor
from sentinel.term import input_text, select
from sentinel.util import truncate

API = "https://api.github.com"


def github_headers(transport: Transport) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = getattr(transport, "github_token", None) or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GitHubMonitor(Monitor):
    kind = "github"
    label = "GitHub repository"
    MONITORS = ("release", "tags", "commits")

    # -- interactive add --------------------------------------------------
    @classmethod
    def default_name(cls, config: dict) -> str:
        return config.get("repo", "github")

    @classmethod
    def prompt(cls, default_monitor: str | None = None) -> dict:
        while True:
            repo = input_text("Repository (owner/name)")
            if "/" in repo and len(repo.split("/")) == 2:
                break
            print("Expected owner/name, e.g. microsoft/vscode")
        if default_monitor:
            monitor = default_monitor
        else:
            monitor = select("Monitor", ["Releases", "Tags", "Commits"]).lower()
        return {"repo": repo, "monitor": monitor}

    # -- fetch ------------------------------------------------------------
    def fetch(self, source: Source, transport: Transport) -> Observation:
        config = source.config
        repo = config.get("repo", "")
        if "/" not in repo:
            raise ConfigError(f"invalid github repo {repo!r} (expected owner/name)")
        monitor = config.get("monitor", "release")
        if monitor not in self.MONITORS:
            raise ConfigError(f"unknown github monitor {monitor!r} (use release, tags or commits)")

        if monitor == "release":
            state = self._fetch_release(repo, transport)
        elif monitor == "tags":
            state = self._fetch_tags(repo, transport)
        else:
            state = self._fetch_commit(repo, transport)
        raw = truncate(json.dumps(state, indent=2, ensure_ascii=False), 4096)
        return Observation(value=state.get("tag") or state.get("sha"), state=state, raw=raw)

    def _get_json(self, transport: Transport, url: str):
        return transport.get_json(url, github_headers(transport))

    def _fetch_release(self, repo: str, transport: Transport) -> dict:
        try:
            data = self._get_json(transport, f"{API}/repos/{repo}/releases/latest")
        except FetchHTTP as exc:
            if exc.status != 404:
                raise
            # No "latest" release (e.g. only prereleases) — fall back to the
            # most recent release of any kind.
            data = self._get_json(transport, f"{API}/repos/{repo}/releases?per_page=1")
            if isinstance(data, list):
                data = data[0] if data else None
        if not data:
            return {"monitor": "release", "tag": None, "releases": []}
        return {
            "monitor": "release",
            "tag": data.get("tag_name"),
            "name": data.get("name") or data.get("tag_name"),
            "published_at": data.get("published_at"),
            "url": data.get("html_url"),
            "prerelease": bool(data.get("prerelease")),
            "assets": [
                {
                    "name": a.get("name"),
                    "size": a.get("size"),
                    "url": a.get("browser_download_url"),
                }
                for a in (data.get("assets") or [])
            ][:100],
        }

    def _fetch_tags(self, repo: str, transport: Transport) -> dict:
        data = self._get_json(transport, f"{API}/repos/{repo}/tags?per_page=1")
        if not data:
            return {"monitor": "tags", "tag": None}
        first = data[0]
        return {
            "monitor": "tags",
            "tag": first.get("name"),
            "sha": (first.get("commit") or {}).get("sha"),
            "url": f"https://github.com/{repo}/tags",
        }

    def _fetch_commit(self, repo: str, transport: Transport) -> dict:
        data = self._get_json(transport, f"{API}/repos/{repo}/commits?per_page=1")
        if not data:
            return {"monitor": "commits", "sha": None}
        first = data[0]
        commit = first.get("commit") or {}
        author = commit.get("author") or {}
        message = (commit.get("message") or "").strip().splitlines()
        return {
            "monitor": "commits",
            "sha": first.get("sha"),
            "short_sha": (first.get("sha") or "")[:8],
            "message": message[0] if message else "",
            "committed_at": author.get("date"),
            "author": author.get("name"),
            "url": first.get("html_url"),
        }

    # -- diff -------------------------------------------------------------
    def diff(self, source: Source, previous: Observation | None, current: Observation) -> list[Change]:
        if previous is None:
            return []
        monitor = source.config.get("monitor", "release")

        if monitor == "commits":
            if previous.value == current.value:
                return []
            sha = current.state.get("short_sha") or (current.value or "")[:7]
            message = current.state.get("message") or ""
            description = f"New commit: {sha} — {message}" if message else f"New commit: {sha}"
            return [Change("commit", previous.value or "—", current.value or "—", description, "info")]

        label = "release" if monitor == "release" else "tag"
        change = ChangeDetector.version(previous.value, current.value, label=label)
        return [change] if change else []


# Register the monitor.
from sentinel.monitors import _registry  # noqa: E402

_registry.register(GitHubMonitor)

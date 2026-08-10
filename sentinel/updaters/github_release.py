"""Updater for GitHub release sources.

Downloads release artifacts from the *official* GitHub release into the
source's configured ``install_path`` (``--install-path`` at add time).
Checksums are verified when the release ships them; unverified downloads
require an explicit ``--allow-unverified`` flag. Nothing is ever executed —
this updater downloads and verifies artifacts only, and records every apply
in the ``updates`` audit table (via the application layer).
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from sentinel.errors import FetchError
from sentinel.httpclient import Transport
from sentinel.models import AssetRef, Source, UpdatePlan, UpdateResult
from sentinel.monitors.github import GitHubMonitor
from sentinel.updaters.base import Updater, VersionProvider
from sentinel.updaters.checksums import find_checksums, is_sum_file, verify_bytes
from sentinel.util import human_size, safe_component

MARKER_FILE = ".sentinel-version"


class GitHubReleaseUpdater(Updater, VersionProvider):
    kind = "github"
    label = "GitHub releases"

    # -- VersionProvider --------------------------------------------------
    def latest_version(self, source: Source, transport: Transport) -> str | None:
        return self._release_state(source, transport).get("tag")

    # -- planning ---------------------------------------------------------
    def plan(self, source: Source, transport: Transport) -> UpdatePlan | None:
        config = source.config
        if config.get("monitor") != "release":
            return UpdatePlan(
                tool=source.name, source=source, kind=self.kind,
                noop=True, noop_reason="only release monitors can be updated",
            )
        install_path = (config.get("install_path") or "").strip()
        if not install_path:
            return None  # caller reports the "not configured for updates" skip

        state = self._release_state(source, transport)
        latest = state.get("tag")
        if not latest:
            return UpdatePlan(
                tool=source.name, source=source, kind=self.kind,
                noop=True, noop_reason="no releases yet",
            )
        installed = self._installed_version(install_path)
        if installed == latest:
            return UpdatePlan(
                tool=source.name, source=source, kind=self.kind,
                installed_version=installed, latest_version=latest,
                noop=True, noop_reason=f"already up to date ({latest})",
            )

        assets = [
            AssetRef(name=a["name"], size=a.get("size"), url=a.get("url"))
            for a in (state.get("assets") or [])
            if a.get("name") and a.get("url")
        ]
        if not assets:
            return UpdatePlan(
                tool=source.name, source=source, kind=self.kind,
                installed_version=installed, latest_version=latest,
                noop=True, noop_reason="release has no downloadable assets",
            )
        patterns = [p for p in (config.get("assets") or []) if p]
        selected = self._select_assets(assets, patterns)

        checksums, note = find_checksums(selected, assets, transport)
        version_dir = Path(install_path).expanduser() / safe_component(latest)
        actions = [
            f"download {a.name} ({human_size(a.size)}) → {version_dir}/" for a in selected
        ]
        return UpdatePlan(
            tool=source.name,
            source=source,
            kind=self.kind,
            installed_version=installed,
            latest_version=latest,
            source_url=state.get("url") or "",
            verified=bool(selected) and len(checksums) == len(selected),
            verify_note=note,
            assets=selected,
            install_path=install_path,
            actions=actions,
            checksums=checksums,
        )

    @staticmethod
    def _select_assets(assets: list[AssetRef], patterns: list[str]) -> list[AssetRef]:
        def checksum_like(a: AssetRef) -> bool:
            name = a.name.lower()
            return name.endswith((".sha256", ".sha512", ".sha256sums", ".sha512sums")) or is_sum_file(name)

        if patterns:
            picked = [
                a for a in assets
                if any(fnmatch.fnmatch(a.name.lower(), p.lower()) or p.lower() in a.name.lower() for p in patterns)
            ]
            return picked
        # No pattern: never auto-select checksum/signature files; pick the
        # primary artifact (largest real asset) rather than guessing.
        real = [a for a in assets if not checksum_like(a)]
        if not real:
            return []
        if len(real) == 1:
            return real
        return [max(real, key=lambda a: a.size or 0)]

    @staticmethod
    def _cleanup(dest: Path) -> None:
        """Remove a freshly created, still-empty version directory on failure."""
        try:
            dest.rmdir()  # only succeeds when empty
        except OSError:
            pass

    @staticmethod
    def _installed_version(install_path: str) -> str | None:
        marker = Path(install_path).expanduser() / MARKER_FILE
        try:
            value = marker.read_text().strip()
            return value or None
        except OSError:
            return None

    def _release_state(self, source: Source, transport: Transport) -> dict:
        return GitHubMonitor().fetch(source, transport).state

    # -- applying ---------------------------------------------------------
    def apply(
        self,
        plan: UpdatePlan,
        transport: Transport,
        *,
        allow_unverified: bool = False,
    ) -> UpdateResult:
        if plan.noop:
            return UpdateResult(source=plan.source, ok=False, message="nothing to apply", status="skipped")
        if not plan.verified and not allow_unverified:
            return UpdateResult(
                source=plan.source,
                ok=False,
                message="download blocked: no verified checksum — rerun with --allow-unverified",
                status="blocked",
            )
        dest = Path(plan.install_path).expanduser() / safe_component(plan.latest_version)
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return UpdateResult(source=plan.source, ok=False, message=f"cannot create {dest}: {exc}", status="failed")

        downloaded: list[str] = []
        for asset in plan.assets:
            filename = Path(asset.name).name  # strip any path components
            if not filename or filename in (".", ".."):
                continue
            try:
                resp = transport.get(asset.url)
            except FetchError as exc:
                self._cleanup(dest)
                return UpdateResult(
                    source=plan.source, ok=False,
                    message=f"download failed for {filename}: {exc.friendly()}", status="failed",
                )
            expected = plan.checksums.get(asset.name)
            if expected and not verify_bytes(resp.body, expected):
                self._cleanup(dest)
                return UpdateResult(
                    source=plan.source, ok=False,
                    message=f"checksum mismatch for {filename} — download discarded", status="failed",
                )
            target = dest / filename
            try:
                target.write_bytes(resp.body)
            except OSError as exc:
                self._cleanup(dest)
                return UpdateResult(source=plan.source, ok=False, message=f"cannot write {target}: {exc}", status="failed")
            downloaded.append(str(target))

        if not downloaded:
            self._cleanup(dest)
            return UpdateResult(source=plan.source, ok=False, message="no assets matched", status="failed")

        marker = Path(plan.install_path).expanduser() / MARKER_FILE
        try:
            marker.write_text(f"{plan.latest_version}\n")
        except OSError:
            pass
        return UpdateResult(
            source=plan.source,
            ok=True,
            message=f"downloaded {plan.latest_version}",
            status="downloaded" if plan.verified else "downloaded-unverified",
            installed_version=plan.latest_version,
            latest_version=plan.latest_version,
            verified=plan.verified,
            downloaded=downloaded,
        )


# Register the updater.
from sentinel.updaters import _registry  # noqa: E402

_registry.register(GitHubReleaseUpdater())

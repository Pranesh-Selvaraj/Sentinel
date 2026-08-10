"""Checksum discovery and verification for downloaded artifacts.

GitHub releases sometimes ship checksums as sibling assets (``app.deb.sha256``)
or as sum files (``SHA256SUMS``, ``checksums.txt``). When a checksum exists we
verify downloads against it; when it does not, downloads are marked unverified
and require an explicit ``--allow-unverified`` flag.
"""

from __future__ import annotations

import hashlib
import re

from sentinel.errors import FetchError
from sentinel.httpclient import Transport
from sentinel.models import AssetRef

SUM_FILE_NAMES = (
    "sha256sums",
    "sha256sums.txt",
    "sha256sums.sha256",
    "sha256sums.sha512",
    "sha256sums.sha256.txt",
    "sha256sum.txt",
    "sha512sum.txt",
    "SHA256SUMS",
    "SHA512SUMS",
    "checksums.txt",
    "checksums-sha256.txt",
    "checksums-sha512.txt",
    "CHECKSUMS",
)

_LINE_RE = re.compile(r"^\s*([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s+\*?\s*(\S+)\s*$", re.MULTILINE)
_HASH_ONLY_RE = re.compile(r"^\s*([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s*$")

_SUM_STEMS = ("sha256sum", "sha512sum", "sha256sums", "sha512sums", "checksums")


def is_sum_file(name: str) -> bool:
    """True for checksum-manifest files: SHA256SUMS, checksums.txt,
    sha256sum.txt, … (case-insensitive)."""
    lowered = name.lower()
    if lowered in SUM_FILE_NAMES:
        return True
    if lowered.endswith((".sha256sums", ".sha512sums")):
        return True
    stem = lowered.split(".")[0]
    return stem in _SUM_STEMS and lowered.endswith((".txt", ".sha256", ".sha512"))


def _basename(path: str) -> str:
    return path.split("/")[-1].lstrip("*")


def find_checksums(
    selected: list[AssetRef], all_assets: list[AssetRef], transport: Transport
) -> tuple[dict, str]:
    """Find checksums for the *selected* assets among *all* release assets.

    Returns ``(checksums, note)`` where ``checksums`` maps each selected asset
    name to ``{"algo": "sha256"|"sha512", "hex": "…"}``.
    """
    sums: dict = {}
    by_name = {a.name: a for a in all_assets}

    # 1) Sibling checksum files: <asset>.sha256 / <asset>.sha512
    for asset in selected:
        for suffix, algo in ((".sha256", "sha256"), (".sha512", "sha512")):
            candidate = by_name.get(asset.name + suffix)
            if not candidate:
                continue
            body = _fetch_text(candidate, transport)
            if body is None:
                continue
            only = _HASH_ONLY_RE.search(body)
            if only:
                sums[asset.name] = {"algo": algo, "hex": only.group(1).lower()}
                break
            for match in _LINE_RE.finditer(body):
                if _basename(match.group(2)) == asset.name:
                    sums[asset.name] = {"algo": algo, "hex": match.group(1).lower()}
                    break
            if asset.name in sums:
                break

    # 2) Sum files covering multiple assets (SHA256SUMS / checksums.txt / …)
    missing = [a for a in selected if a.name not in sums]
    if missing:
        missing_names = {a.name for a in missing}
        for candidate in all_assets:
            if not is_sum_file(candidate.name):
                continue
            algo = "sha512" if "sha512" in candidate.name.lower() else "sha256"
            body = _fetch_text(candidate, transport)
            if body is None:
                continue
            for match in _LINE_RE.finditer(body):
                name = _basename(match.group(2))
                if name in missing_names:
                    sums.setdefault(name, {"algo": algo, "hex": match.group(1).lower()})

    verified = bool(selected) and len(sums) == len(selected)
    note = (
        "checksum verified (sha256/sha512)"
        if verified
        else "no checksum available — requires --allow-unverified"
    )
    return sums, note


def _fetch_text(asset: AssetRef, transport: Transport) -> str | None:
    try:
        return transport.get(asset.url).body.decode("utf-8", "replace")
    except FetchError:
        return None


def verify_bytes(data: bytes, expected: dict) -> bool:
    """Verify *data* against an expected ``{"algo", "hex"}`` digest."""
    algo = str(expected.get("algo") or "sha256")
    digest = hashlib.new(algo, data).hexdigest()
    return digest.lower() == str(expected.get("hex") or "").lower()

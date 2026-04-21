"""Self-updater — checks GitHub Releases and runs a new installer.

Flow
----
1. ``check_latest()`` hits ``/repos/OWNER/REPO/releases/latest`` on the
   GitHub API and parses ``tag_name`` + the ``.exe`` asset.
2. If the tag is newer than the bundled ``__version__``, ask the user.
3. On yes, download the installer to ``%TEMP%``. If a ``*.sha256`` asset
   is also present, verify it before launching.
4. Launch Inno Setup with ``/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS``.
   The installer will stop the tray + service itself, replace files, then
   restart everything.

No external dependencies — urllib only. Safe to call from the tray thread
but the network + download run in a background worker so the UI doesn't
freeze.
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from face_service._version import __version__
from face_service.i18n import t

log = logging.getLogger(__name__)

GITHUB_OWNER = "caochitam"
GITHUB_REPO = "windows-face-unlock"
RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"windows-face-unlock/{__version__} (updater)"
INSTALLER_SUFFIX = ".exe"


@dataclass
class ReleaseInfo:
    tag: str                # e.g. "v0.2.0"
    version: str            # e.g. "0.2.0"
    body: str               # release notes (markdown)
    asset_name: str         # installer filename
    asset_url: str          # browser_download_url
    checksum_url: str | None  # optional .sha256 sibling

    def is_newer_than(self, current: str) -> bool:
        return _parse_version(self.version) > _parse_version(current)


_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.].*)?$")


def _parse_version(v: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match(v.strip())
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _http_get(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check_latest(timeout: float = 10.0) -> ReleaseInfo | None:
    """Fetch the latest release. Returns None on any error (callers warn)."""
    try:
        payload = json.loads(_http_get(RELEASES_LATEST_URL, timeout=timeout))
    except urllib.error.HTTPError as e:
        log.warning("releases/latest HTTP %s: %s", e.code, e)
        return None
    except Exception:
        log.exception("releases/latest fetch failed")
        return None

    tag = payload.get("tag_name") or ""
    version = tag.lstrip("v")
    body = payload.get("body") or ""
    assets = payload.get("assets") or []

    installer = None
    checksum_url = None
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(INSTALLER_SUFFIX):
            installer = a
        if name.endswith(".sha256") or name.endswith(".sha256.txt"):
            checksum_url = a.get("browser_download_url")

    if not (tag and installer):
        log.info("latest release %s has no installer asset", tag)
        return None

    return ReleaseInfo(
        tag=tag,
        version=version,
        body=body,
        asset_name=installer.get("name") or "installer.exe",
        asset_url=installer.get("browser_download_url") or "",
        checksum_url=checksum_url,
    )


def _download(url: str, dest: Path,
              progress: Callable[[int, int], None] | None = None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30.0) as resp, dest.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        seen = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            seen += len(chunk)
            if progress:
                try:
                    progress(seen, total)
                except Exception:
                    pass


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(url: str) -> str | None:
    try:
        raw = _http_get(url).decode("utf-8", errors="replace").strip()
    except Exception:
        log.exception("checksum fetch failed")
        return None
    # Accept either raw hex, or "<hex>  filename" style.
    token = raw.split()[0] if raw else ""
    if re.fullmatch(r"[0-9a-fA-F]{64}", token):
        return token.lower()
    return None


def download_and_launch(
    release: ReleaseInfo,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[bool, str]:
    """Download the installer, verify checksum (if any), and spawn it.

    Returns (ok, message). On ok=True, the caller should exit the tray —
    the installer will kill any lingering processes itself.
    """
    tmp_dir = Path(tempfile.gettempdir()) / "windows-face-unlock-update"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / release.asset_name

    try:
        _download(release.asset_url, dest, progress=progress)
    except Exception as e:
        return False, t("update.download_failed", err=str(e))

    if release.checksum_url:
        expected = _expected_sha256(release.checksum_url)
        if expected and _sha256_of(dest) != expected:
            try:
                dest.unlink()
            except Exception:
                pass
            return False, t("update.checksum_failed")

    # Launch silently. The installer itself signals CloseApplications so
    # any running tray/service gets stopped before files are replaced.
    try:
        subprocess.Popen(
            [str(dest), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
        )
    except Exception as e:
        return False, t("update.download_failed", err=str(e))

    return True, t("update.launching")


def current_version() -> str:
    return __version__

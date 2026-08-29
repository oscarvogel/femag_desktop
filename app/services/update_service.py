from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MANIFEST_URL = "https://raw.githubusercontent.com/oscarvogel/vogel-releases/main/apps/femag/latest.json"
EXPECTED_APP_ID = "femag"
DEFAULT_TIMEOUT_SECONDS = 6
INSTALLER_FILENAME = "FEMAG_Desktop_Produccion_Setup.exe"
VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    sha256: str
    notes: str = ""
    mandatory: bool = False


def _version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value.strip()):
        return ()
    return tuple(int(part) for part in value.strip().split("."))


def is_newer_version(current_version: str, candidate_version: str) -> bool:
    current = _version_tuple(current_version)
    candidate = _version_tuple(candidate_version)
    return bool(current and candidate and candidate > current)


def _is_https(url: str) -> bool:
    return urllib.parse.urlparse(url).scheme.lower() == "https"


def fetch_update_info(
    current_version: str,
    *,
    manifest_url: str = MANIFEST_URL,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., object] | None = None,
) -> UpdateInfo | None:
    if not _is_https(manifest_url):
        raise ValueError("El manifest de actualizacion debe usar HTTPS.")

    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "FEMAG-Desktop-Updater/1"},
    )
    with open_url(request, timeout=timeout) as response:  # type: ignore[misc]
        raw = response.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("El manifest debe ser UTF-8 sin BOM.")
    payload = json.loads(raw.decode("utf-8"))

    if payload.get("schema_version") != 1:
        return None
    if str(payload.get("app_id", "")).strip() != EXPECTED_APP_ID:
        return None

    candidate = UpdateInfo(
        version=str(payload.get("version", "")).strip(),
        download_url=str(payload.get("download_url", "")).strip(),
        sha256=str(payload.get("sha256", "")).strip().lower(),
        notes=str(payload.get("notes", "")).strip(),
        mandatory=bool(payload.get("mandatory", False)),
    )
    if not VERSION_RE.fullmatch(candidate.version):
        return None
    if not _is_https(candidate.download_url):
        return None
    if not SHA256_RE.fullmatch(candidate.sha256):
        return None
    if not is_newer_version(current_version, candidate.version):
        return None
    return candidate


def download_installer(
    update: UpdateInfo,
    *,
    destination_dir: Path | None = None,
    timeout: int = 60,
    opener: Callable[..., object] | None = None,
) -> Path:
    if not _is_https(update.download_url):
        raise ValueError("El instalador debe descargarse mediante HTTPS.")
    if not SHA256_RE.fullmatch(update.sha256):
        raise ValueError("El SHA256 publicado no es valido.")

    target_dir = destination_dir or Path(tempfile.gettempdir()) / "FEMAG Desktop" / "updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / INSTALLER_FILENAME
    partial = target.with_suffix(".exe.part")
    partial.unlink(missing_ok=True)

    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        update.download_url,
        headers={"User-Agent": "FEMAG-Desktop-Updater/1"},
    )
    digest = hashlib.sha256()
    try:
        with open_url(request, timeout=timeout) as response, partial.open("wb") as handle:  # type: ignore[misc]
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)

        actual = digest.hexdigest().lower()
        if actual != update.sha256.lower():
            raise ValueError("El instalador descargado no coincide con el SHA256 publicado.")
        os.replace(partial, target)
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        raise

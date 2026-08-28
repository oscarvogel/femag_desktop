from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


MANIFEST_URL = "https://raw.githubusercontent.com/oscarvogel/vogel-releases/main/apps/femag/latest.json"
DEFAULT_TIMEOUT_SECONDS = 6


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    sha256: str
    notes: str = ""
    mandatory: bool = False


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except (TypeError, ValueError):
        return ()


def is_newer_version(current_version: str, candidate_version: str) -> bool:
    current = _version_tuple(current_version)
    candidate = _version_tuple(candidate_version)
    return bool(current and candidate and candidate > current)


def fetch_update_info(
    current_version: str,
    *,
    manifest_url: str = MANIFEST_URL,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., object] | None = None,
) -> UpdateInfo | None:
    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "FEMAG-Desktop-Updater/1"},
    )
    with open_url(request, timeout=timeout) as response:  # type: ignore[misc]
        # utf-8-sig acepta manifests con o sin BOM. Windows PowerShell 5.1 puede
        # escribir UTF-8 con BOM, por lo que el cliente debe ser tolerante.
        payload = json.loads(response.read().decode("utf-8-sig"))

    candidate = UpdateInfo(
        version=str(payload.get("version", "")).strip(),
        download_url=str(payload.get("download_url", "")).strip(),
        sha256=str(payload.get("sha256", "")).strip().lower(),
        notes=str(payload.get("notes", "")).strip(),
        mandatory=bool(payload.get("mandatory", False)),
    )
    if not candidate.version or not candidate.download_url or len(candidate.sha256) != 64:
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
    target_dir = destination_dir or Path(tempfile.gettempdir()) / "FEMAG Desktop" / "updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "FEMAG_Desktop_Produccion_Setup.exe"
    partial = target.with_suffix(".exe.part")

    open_url = opener or urllib.request.urlopen
    request = urllib.request.Request(
        update.download_url,
        headers={"User-Agent": "FEMAG-Desktop-Updater/1"},
    )
    digest = hashlib.sha256()
    with open_url(request, timeout=timeout) as response, partial.open("wb") as handle:  # type: ignore[misc]
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)

    actual = digest.hexdigest().lower()
    if actual != update.sha256.lower():
        partial.unlink(missing_ok=True)
        raise ValueError("El instalador descargado no coincide con el SHA256 publicado.")

    os.replace(partial, target)
    return target

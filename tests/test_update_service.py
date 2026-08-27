import hashlib
import io
import json

import pytest

from app.services.update_service import UpdateInfo, download_installer, fetch_update_info, is_newer_version


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _opener_for(payload: bytes):
    def _open(_request, timeout=None):
        return _Response(payload)
    return _open


def test_version_comparison_supports_timestamp_builds():
    assert is_newer_version("2026.08.26.14.40.56", "2026.08.27.09.10.11")
    assert not is_newer_version("2026.08.27.09.10.11", "2026.08.26.14.40.56")
    assert not is_newer_version("2026.08.27.09.10.11", "2026.08.27.09.10.11")


def test_fetch_update_info_returns_only_newer_valid_manifest():
    payload = json.dumps({
        "version": "2026.08.28.10.00.00",
        "download_url": "https://example.invalid/FEMAG_Desktop_Produccion_Setup.exe",
        "sha256": "a" * 64,
        "notes": "Nueva versión",
        "mandatory": False,
    }).encode()

    info = fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(payload))

    assert info is not None
    assert info.version == "2026.08.28.10.00.00"
    assert info.notes == "Nueva versión"


def test_fetch_update_info_ignores_same_or_older_version():
    payload = json.dumps({
        "version": "2026.08.27.10.00.00",
        "download_url": "https://example.invalid/setup.exe",
        "sha256": "b" * 64,
    }).encode()

    assert fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(payload)) is None


def test_download_installer_validates_sha256(tmp_path):
    body = b"fake-inno-installer"
    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256=hashlib.sha256(body).hexdigest(),
    )

    path = download_installer(info, destination_dir=tmp_path, opener=_opener_for(body))

    assert path.name == "FEMAG_Desktop_Produccion_Setup.exe"
    assert path.read_bytes() == body


def test_download_installer_rejects_bad_sha256(tmp_path):
    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="SHA256"):
        download_installer(info, destination_dir=tmp_path, opener=_opener_for(b"tampered"))

    assert not (tmp_path / "FEMAG_Desktop_Produccion_Setup.exe").exists()

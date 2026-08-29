import hashlib
import io
import json

import pytest

from app.services.update_service import (
    CANDIDATE_CHANNEL,
    CANDIDATE_MANIFEST_URL,
    LATEST_CHANNEL,
    LATEST_MANIFEST_URL,
    UpdateInfo,
    candidate_receipt_matches,
    download_installer,
    fetch_update_info,
    get_update_channel,
    is_newer_version,
    manifest_url_for_channel,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _opener_for(payload: bytes):
    def _open(_request, timeout=None):
        return _Response(payload)
    return _open


def _manifest(**overrides):
    payload = {
        "schema_version": 1,
        "app_id": "femag",
        "version": "2026.08.28.10.00.00",
        "download_url": "https://example.invalid/FEMAG_Desktop_Produccion_Setup.exe",
        "sha256": "a" * 64,
        "notes": "Nueva versión",
        "mandatory": False,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_version_comparison_supports_timestamp_builds():
    assert is_newer_version("2026.08.26.14.40.56", "2026.08.27.09.10.11")
    assert not is_newer_version("2026.08.27.09.10.11", "2026.08.26.14.40.56")
    assert not is_newer_version("2026.08.27.09.10.11", "2026.08.27.09.10.11")
    assert not is_newer_version("invalid", "2026.08.27.09.10.11")
    assert not is_newer_version("2026.08.27.09.10.11", "invalid")


def test_default_channel_is_latest_and_candidate_is_explicit(monkeypatch):
    monkeypatch.delenv("FEMAG_UPDATE_CHANNEL", raising=False)
    assert get_update_channel() == LATEST_CHANNEL
    assert manifest_url_for_channel() == LATEST_MANIFEST_URL
    monkeypatch.setenv("FEMAG_UPDATE_CHANNEL", "candidate")
    assert get_update_channel() == CANDIDATE_CHANNEL
    assert manifest_url_for_channel() == CANDIDATE_MANIFEST_URL


def test_unknown_channel_falls_back_to_latest(monkeypatch):
    monkeypatch.setenv("FEMAG_UPDATE_CHANNEL", "anything-else")
    assert get_update_channel() == LATEST_CHANNEL
    assert manifest_url_for_channel() == LATEST_MANIFEST_URL


def test_fetch_update_info_returns_newer_valid_manifest():
    info = fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(_manifest()))
    assert info is not None
    assert info.version == "2026.08.28.10.00.00"
    assert info.notes == "Nueva versión"
    assert info.channel == LATEST_CHANNEL


def test_fetch_candidate_requires_candidate_identity_when_explicit():
    info = fetch_update_info(
        "2026.08.27.10.00.00",
        channel=CANDIDATE_CHANNEL,
        opener=_opener_for(_manifest(channel="candidate")),
    )
    assert info is not None
    assert info.channel == CANDIDATE_CHANNEL
    assert fetch_update_info(
        "2026.08.27.10.00.00",
        channel=CANDIDATE_CHANNEL,
        opener=_opener_for(_manifest(channel="latest")),
    ) is None


def test_fetch_update_info_ignores_same_or_older_version():
    assert fetch_update_info("2026.08.28.10.00.00", opener=_opener_for(_manifest())) is None
    older = _manifest(version="2026.08.27.10.00.00")
    assert fetch_update_info("2026.08.28.10.00.00", opener=_opener_for(older)) is None


def test_fetch_update_info_rejects_wrong_schema_and_app_id():
    assert fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(_manifest(schema_version=2))) is None
    assert fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(_manifest(app_id="fgpy"))) is None


def test_fetch_update_info_rejects_invalid_version_sha_and_http_download():
    assert fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(_manifest(version="v2"))) is None
    assert fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(_manifest(sha256="z" * 64))) is None
    assert fetch_update_info(
        "2026.08.27.10.00.00",
        opener=_opener_for(_manifest(download_url="http://example.invalid/setup.exe")),
    ) is None


def test_fetch_update_info_requires_https_manifest():
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_update_info("2026.08.27.10.00.00", manifest_url="http://example.invalid/latest.json")


def test_fetch_update_info_rejects_utf8_bom_manifest():
    with pytest.raises(ValueError, match="BOM"):
        fetch_update_info("2026.08.27.10.00.00", opener=_opener_for(b"\xef\xbb\xbf" + _manifest()))


def test_download_installer_validates_sha256_and_uses_atomic_target(tmp_path, monkeypatch):
    monkeypatch.setenv("FEMAG_RUNTIME_DIR", str(tmp_path / "runtime"))
    body = b"fake-inno-installer"
    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256=hashlib.sha256(body).hexdigest(),
    )
    path = download_installer(info, destination_dir=tmp_path, opener=_opener_for(body))
    assert path.name == "FEMAG_Desktop_Produccion_Setup.exe"
    assert path.read_bytes() == body
    assert not (tmp_path / "FEMAG_Desktop_Produccion_Setup.exe.part").exists()


def test_candidate_download_persists_exact_version_sha_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("FEMAG_RUNTIME_DIR", str(tmp_path / "runtime"))
    body = b"candidate-installer"
    sha = hashlib.sha256(body).hexdigest()
    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256=sha,
        channel=CANDIDATE_CHANNEL,
    )
    download_installer(info, destination_dir=tmp_path / "download", opener=_opener_for(body))
    assert candidate_receipt_matches(version=info.version, sha256=sha)
    assert not candidate_receipt_matches(version="2026.08.28.10.00.01", sha256=sha)
    assert not candidate_receipt_matches(version=info.version, sha256="0" * 64)


def test_download_installer_rejects_bad_sha256_and_cleans_part(tmp_path, monkeypatch):
    monkeypatch.setenv("FEMAG_RUNTIME_DIR", str(tmp_path / "runtime"))
    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="SHA256"):
        download_installer(info, destination_dir=tmp_path, opener=_opener_for(b"tampered"))
    assert not (tmp_path / "FEMAG_Desktop_Produccion_Setup.exe").exists()
    assert not (tmp_path / "FEMAG_Desktop_Produccion_Setup.exe.part").exists()


def test_download_installer_rejects_invalid_sha_and_http(tmp_path):
    with pytest.raises(ValueError, match="SHA256"):
        download_installer(UpdateInfo("2026.08.28.10.00.00", "https://example.invalid/a.exe", "x" * 64), destination_dir=tmp_path)
    with pytest.raises(ValueError, match="HTTPS"):
        download_installer(UpdateInfo("2026.08.28.10.00.00", "http://example.invalid/a.exe", "a" * 64), destination_dir=tmp_path)


def test_download_installer_cleans_stale_and_failed_part(tmp_path):
    partial = tmp_path / "FEMAG_Desktop_Produccion_Setup.exe.part"
    partial.write_bytes(b"stale")

    def failing_opener(_request, timeout=None):
        raise OSError("network down")

    info = UpdateInfo(
        version="2026.08.28.10.00.00",
        download_url="https://example.invalid/setup.exe",
        sha256="a" * 64,
    )
    with pytest.raises(OSError, match="network down"):
        download_installer(info, destination_dir=tmp_path, opener=failing_opener)
    assert not partial.exists()

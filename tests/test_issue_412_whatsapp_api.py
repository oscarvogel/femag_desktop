from __future__ import annotations

from pathlib import Path

import pytest


def test_whatsapp_config_reads_single_local_env(monkeypatch, tmp_path):
    from app.services.whatsapp_api_client import WhatsAppApiClient

    env_file = tmp_path / ".env"
    env_file.write_text(
        "WHATSAPP_ENABLED=true\n"
        "WHATSAPP_API_URL=https://gateway.example\n"
        "WHATSAPP_API_KEY=secret-local-only\n"
        "WHATSAPP_INSTANCE_ID=default\n"
        "WHATSAPP_API_TIMEOUT=21\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FEMAG_ENV_FILE", str(env_file))

    client = WhatsAppApiClient()

    assert client.config.base_url == "https://gateway.example"
    assert client.config.api_key == "secret-local-only"
    assert client.config.instance_id == "default"
    assert client.config.timeout_seconds == 21


def test_whatsapp_is_disabled_by_default(monkeypatch, tmp_path):
    from app.services.whatsapp_api_client import WhatsAppApiClient, WhatsAppApiError

    env_file = tmp_path / ".env"
    env_file.write_text("WHATSAPP_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setenv("FEMAG_ENV_FILE", str(env_file))

    with pytest.raises(WhatsAppApiError, match="deshabilitado"):
        WhatsAppApiClient()


def test_normalize_phone_supports_argentina_mobile():
    from app.services.whatsapp_envio_service import normalize_phone

    assert normalize_phone("03743 15 123456") == "5493743123456"
    assert normalize_phone("+54 9 3743 123456") == "5493743123456"


def test_whatsapp_envio_persists_message_and_tracking(db, tmp_path):
    from app.models.security import User, UserProfile
    from app.services.whatsapp_envio_service import WhatsAppEnvioService

    class FakeClient:
        def upload_document(self, **kwargs):
            assert kwargs["external_ref"].startswith("femag:extracto_cuenta:")
            assert Path(kwargs["file_path"]).read_bytes() == b"%PDF-test"
            return {"messageId": "msg-123", "status": "queued"}

        def get_message(self, message_id):
            assert message_id == "msg-123"
            return {
                "status": "read",
                "providerMessageId": "prov-456",
                "acceptedAt": "2026-09-10T18:00:00.000Z",
                "deliveredAt": "2026-09-10T18:00:01.000Z",
                "readAt": "2026-09-10T18:00:02.000Z",
            }

    profile = UserProfile.create(name="Administrador whatsapp")
    user = User.create(username="wa-user", password_hash="x", profile=profile)
    pdf = tmp_path / "extracto.pdf"
    pdf.write_bytes(b"%PDF-test")
    service = WhatsAppEnvioService(client=FakeClient())
    envio = service.create_attempt(
        tipo_documento="extracto_cuenta",
        documento_id="cliente-9",
        destinatario="+54 9 3743 123456",
        caption="FEMAG - Extracto",
        pdf_path=pdf,
        usuario=user,
    )

    result = service.send_pdf(envio=envio, pdf_path=pdf, poll_attempts=1, poll_interval=0)

    assert result.message_id == "msg-123"
    assert result.provider_message_id == "prov-456"
    assert result.estado == "read"
    assert result.read_at is not None
    assert result.external_ref == f"femag:extracto_cuenta:cliente-9:{result.id}"

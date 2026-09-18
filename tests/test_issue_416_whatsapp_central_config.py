from __future__ import annotations


def test_central_whatsapp_configuration_is_encrypted_in_app_parameters(db, monkeypatch):
    from app.models.system import AppParameter
    from app.services.whatsapp_configuration_service import (
        WhatsAppCentralConfiguration,
        WhatsAppCentralConfigurationService,
    )

    monkeypatch.setenv("DB_PASSWORD", "mysql-secret-for-tests")
    configuration = WhatsAppCentralConfiguration(
        api_url="https://whatsapp.vogelconsultoria.com.ar/",
        api_key="femag-api-key-super-secreta",
        timeout_seconds=25,
        enabled=True,
    )

    WhatsAppCentralConfigurationService.save(configuration)
    loaded = WhatsAppCentralConfigurationService.load()

    assert loaded == WhatsAppCentralConfiguration(
        api_url="https://whatsapp.vogelconsultoria.com.ar",
        api_key="femag-api-key-super-secreta",
        timeout_seconds=25.0,
        enabled=True,
    )
    encrypted = AppParameter.get(
        AppParameter.key == "whatsapp.api_key_encrypted"
    ).value
    assert encrypted
    assert "femag-api-key-super-secreta" not in encrypted
    assert AppParameter.get(
        AppParameter.key == "whatsapp.secret_format"
    ).value == "fernet-db-password-v1"


def test_api_client_prefers_central_database_configuration(db, monkeypatch):
    from app.services.whatsapp_api_client import WhatsAppApiConfig
    from app.services.whatsapp_configuration_service import (
        WhatsAppCentralConfiguration,
        WhatsAppCentralConfigurationService,
    )

    monkeypatch.setenv("DB_PASSWORD", "mysql-secret-for-tests")
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_API_URL", "https://legacy-env.example")
    monkeypatch.setenv("WHATSAPP_API_KEY", "legacy-key")
    monkeypatch.setenv("WHATSAPP_INSTANCE_ID", "legacy-instance")
    WhatsAppCentralConfigurationService.save(
        WhatsAppCentralConfiguration(
            api_url="https://central.example",
            api_key="central-key",
            timeout_seconds=19,
            enabled=True,
        )
    )

    config = WhatsAppApiConfig.from_settings()

    assert config.base_url == "https://central.example"
    assert config.api_key == "central-key"
    assert config.timeout_seconds == 19
    assert config.instance_id is None


def test_user_can_have_whatsapp_instance_and_envio_keeps_snapshot(db):
    from app.models.security import User, UserProfile
    from app.services.whatsapp_envio_service import WhatsAppEnvioService

    class FakeClient:
        config = type("Config", (), {"instance_id": None})()

    profile = UserProfile.create(name="Administrador issue 416")
    user = User.create(
        username="oscar",
        password_hash="x",
        profile=profile,
        whatsapp_instance_id="femag_oscar",
    )
    service = WhatsAppEnvioService(client=FakeClient())

    envio = service.create_attempt(
        tipo_documento="orden_carga",
        documento_id="621",
        destinatario="+54 9 376 4123456",
        caption="Orden de carga",
        pdf_path=__import__("pathlib").Path("orden-621.pdf"),
        usuario=user,
    )

    assert envio.instance_id == "femag_oscar"

    user.whatsapp_instance_id = "femag_oscar_nueva"
    user.save()
    envio = type(envio).get_by_id(envio.id)
    assert envio.instance_id == "femag_oscar"



def test_envio_uses_latest_persisted_user_instance_when_session_object_is_stale(db):
    from app.models.security import User, UserProfile
    from app.services.whatsapp_envio_service import WhatsAppEnvioService

    class FakeClient:
        config = type("Config", (), {"instance_id": None})()

    profile = UserProfile.create(name="Administrador issue 480")
    User.create(
        username="oscar-stale",
        password_hash="x",
        profile=profile,
        whatsapp_instance_id="instancia-anterior",
    )
    session_user = User.get(User.username == "oscar-stale")
    updated_user = User.get_by_id(session_user.id)
    updated_user.whatsapp_instance_id = "oscar_claro_2"
    updated_user.save(only=[User.whatsapp_instance_id])

    assert session_user.whatsapp_instance_id == "instancia-anterior"

    envio = WhatsAppEnvioService(client=FakeClient()).create_attempt(
        tipo_documento="extracto_cuenta",
        documento_id="cliente-480",
        destinatario="+54 9 376 4123456",
        caption="Extracto de cuenta corriente",
        pdf_path=__import__("pathlib").Path("extracto-cliente-480.pdf"),
        usuario=session_user,
    )

    assert envio.instance_id == "oscar_claro_2"

def test_user_without_instance_is_rejected_when_there_is_no_legacy_instance(db):
    import pytest

    from app.models.security import User, UserProfile
    from app.services.whatsapp_envio_service import WhatsAppEnvioService

    class FakeClient:
        config = type("Config", (), {"instance_id": None})()

    profile = UserProfile.create(name="Secretaría issue 416")
    user = User.create(username="sin-wa", password_hash="x", profile=profile)
    service = WhatsAppEnvioService(client=FakeClient())

    with pytest.raises(ValueError, match="no tiene una instancia"):
        service.create_attempt(
            tipo_documento="orden_carga",
            documento_id="622",
            destinatario="+54 9 376 4123456",
            caption="Orden de carga",
            pdf_path=__import__("pathlib").Path("orden-622.pdf"),
            usuario=user,
        )



def test_send_text_uses_selected_instance(monkeypatch):
    import io
    import json

    from app.services.whatsapp_api_client import WhatsAppApiClient, WhatsAppApiConfig

    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"success": True, "data": {"messageId": "test-123", "status": "queued"}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.whatsapp_api_client.urlopen", fake_urlopen)

    client = WhatsAppApiClient(
        WhatsAppApiConfig(
            base_url="https://gateway.example",
            api_key="secret-key",
            timeout_seconds=17,
            enabled=True,
        )
    )
    result = client.send_text(
        phone="5493764123456",
        message="Prueba FEMAG",
        instance_id="femag_oscar",
        external_ref="femag:test:1",
        actor_id="1",
        actor_name="Oscar",
    )

    assert captured["url"] == (
        "https://gateway.example/api/v1/instances/femag_oscar/messages"
    )
    assert captured["body"]["phone"] == "5493764123456"
    assert captured["body"]["message"] == "Prueba FEMAG"
    assert captured["body"]["externalRef"] == "femag:test:1"
    assert captured["body"]["actorId"] == "1"
    assert captured["body"]["actorName"] == "Oscar"
    assert captured["body"]["sourceApp"] == "femag_desktop"
    assert captured["timeout"] == 17
    assert result == {"messageId": "test-123", "status": "queued"}

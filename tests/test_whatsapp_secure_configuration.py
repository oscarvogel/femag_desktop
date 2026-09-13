import json


def test_runtime_whatsapp_configuration_splits_metadata_from_api_key(tmp_path, monkeypatch):
    from app.config import secure_credentials
    from app.config.secure_credentials import RuntimeWhatsAppConfiguration

    monkeypatch.setattr(
        secure_credentials,
        "protect_secret",
        lambda value, **_kwargs: b"dpapi:" + value[::-1].encode(),
    )
    monkeypatch.setattr(
        secure_credentials,
        "unprotect_secret",
        lambda value: value.removeprefix(b"dpapi:")[::-1].decode(),
    )
    configuration = RuntimeWhatsAppConfiguration(
        api_url="https://whatsapp.femag.example/",
        api_key="clave-privada",
        instance_id="default",
        timeout_seconds=20,
        enabled=True,
    )

    secure_credentials.save_runtime_whatsapp_configuration(configuration, tmp_path)

    metadata = json.loads((tmp_path / "whatsapp.json").read_text(encoding="utf-8"))
    credential = (tmp_path / "whatsapp.credential").read_bytes()
    assert metadata == {
        "version": 1,
        "enabled": True,
        "api_url": "https://whatsapp.femag.example",
        "instance_id": "default",
        "timeout_seconds": 20.0,
    }
    assert "clave-privada" not in json.dumps(metadata)
    assert b"clave-privada" not in credential
    assert secure_credentials.load_runtime_whatsapp_configuration(tmp_path) == RuntimeWhatsAppConfiguration(
        api_url="https://whatsapp.femag.example",
        api_key="clave-privada",
        instance_id="default",
        timeout_seconds=20.0,
        enabled=True,
    )


def test_secure_whatsapp_configuration_overrides_env(monkeypatch):
    from app.config import secure_credentials
    from app.config.secure_credentials import RuntimeWhatsAppConfiguration
    from app.services.whatsapp_api_client import WhatsAppApiConfig

    monkeypatch.setattr(
        secure_credentials,
        "load_runtime_whatsapp_configuration",
        lambda: RuntimeWhatsAppConfiguration(
            api_url="https://secure-gateway.example",
            api_key="secure-key",
            instance_id="shared-instance",
            timeout_seconds=22,
            enabled=True,
        ),
    )
    monkeypatch.setattr(secure_credentials, "has_runtime_whatsapp_configuration", lambda: True)
    monkeypatch.setenv("WHATSAPP_ENABLED", "false")
    monkeypatch.setenv("WHATSAPP_API_URL", "https://plain-text.example")
    monkeypatch.setenv("WHATSAPP_API_KEY", "plain-text-key")

    configuration = WhatsAppApiConfig.from_settings()

    assert configuration.base_url == "https://secure-gateway.example"
    assert configuration.api_key == "secure-key"
    assert configuration.instance_id == "shared-instance"
    assert configuration.timeout_seconds == 22
    assert configuration.enabled is True


def test_invalid_secure_whatsapp_configuration_does_not_fall_back_to_env(monkeypatch):
    from app.config import secure_credentials
    from app.config.secure_credentials import SecureConfigurationError
    from app.services.whatsapp_api_client import WhatsAppApiConfig

    monkeypatch.setattr(secure_credentials, "has_runtime_whatsapp_configuration", lambda: True)
    monkeypatch.setattr(
        secure_credentials,
        "load_runtime_whatsapp_configuration",
        lambda: (_ for _ in ()).throw(SecureConfigurationError("API key protegida inválida")),
    )
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")

    import pytest

    with pytest.raises(SecureConfigurationError, match="inválida"):
        WhatsAppApiConfig.from_settings()


def test_whatsapp_configuration_preserves_existing_key_when_rotation_is_empty():
    from app.config.secure_credentials import RuntimeWhatsAppConfiguration
    from app.ui.whatsapp_configuration import WhatsAppConfigurationDialog

    current = RuntimeWhatsAppConfiguration(
        api_url="https://gateway.example",
        api_key="previous-key",
        instance_id="default",
        timeout_seconds=15,
        enabled=True,
    )
    class Field:
        def __init__(self, value):
            self._value = value

        def text(self):
            return self._value

    class Toggle:
        def isChecked(self):
            return True

    class Timeout:
        def value(self):
            return 15

    dialog = type(
        "DialogValues",
        (),
        {
            "_current": current,
            "api_key": Field(""),
            "api_url": Field("https://gateway.example"),
            "instance_id": Field("default"),
            "timeout": Timeout(),
            "enabled": Toggle(),
        },
    )()

    configuration = WhatsAppConfigurationDialog.configuration(dialog)
    assert configuration.api_key == "previous-key"


def test_whatsapp_configuration_audit_omits_api_key(db):
    from app.config.secure_credentials import RuntimeWhatsAppConfiguration
    from app.models.audit import AuditLog
    from app.services.audit_service import AuditService
    from app.ui.whatsapp_configuration import _audit_value

    configuration = RuntimeWhatsAppConfiguration(
        api_url="https://gateway.example",
        api_key="rotated-key",
        instance_id="default",
        timeout_seconds=30,
        enabled=True,
    )

    AuditService().record(
        user="admin_whatsapp_config",
        module="WhatsApp",
        action="configurar",
        new_value=_audit_value(configuration),
        observation="Configuración local de WhatsApp actualizada; API key protegida y omitida.",
    )

    audit = AuditLog.get(AuditLog.action == "configurar")
    assert audit.module == "WhatsApp"
    assert audit.user == "admin_whatsapp_config"
    assert audit.new_value["api_key"] == "protected"
    assert "rotated-key" not in str(audit.new_value)
    assert "rotated-key" not in (audit.observation or "")

import json
import os


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def test_whatsapp_configuration_dialog_preserves_hidden_key():
    from PyQt5.QtWidgets import QApplication, QLineEdit

    from app.config.secure_credentials import RuntimeWhatsAppConfiguration
    from app.ui.whatsapp_configuration import WhatsAppConfigurationDialog

    current = RuntimeWhatsAppConfiguration(
        api_url="https://gateway.example",
        api_key="previous-key",
        instance_id="default",
        timeout_seconds=15,
        enabled=True,
    )
    app = QApplication.instance() or QApplication([])
    dialog = WhatsAppConfigurationDialog(current=current)

    assert dialog.api_key.echoMode() == QLineEdit.Password
    assert dialog.api_key.text() == ""
    assert dialog.configuration().api_key == "previous-key"
    dialog.api_key.setText("rotated-key")
    assert dialog.configuration().api_key == "rotated-key"
    app.processEvents()


def test_whatsapp_configuration_page_audits_without_api_key(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.config.secure_credentials import RuntimeWhatsAppConfiguration, SecureConfigurationError
    from app.models.audit import AuditLog
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui import whatsapp_configuration

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_whatsapp_config", password_hash="x", profile=profile)
    saved = []
    configuration = RuntimeWhatsAppConfiguration(
        api_url="https://gateway.example",
        api_key="rotated-key",
        instance_id="default",
        timeout_seconds=30,
        enabled=True,
    )

    monkeypatch.setattr(whatsapp_configuration, "has_runtime_whatsapp_configuration", lambda: False)
    monkeypatch.setattr(
        whatsapp_configuration,
        "load_runtime_whatsapp_configuration",
        lambda: (_ for _ in ()).throw(SecureConfigurationError("sin configuración")),
    )
    monkeypatch.setattr(
        whatsapp_configuration,
        "save_runtime_whatsapp_configuration",
        saved.append,
    )
    monkeypatch.setattr(whatsapp_configuration.QMessageBox, "information", lambda *_args: None)

    class FakeDialog:
        def __init__(self, **_kwargs):
            pass

        def exec_(self):
            return QDialog.Accepted

        def configuration(self):
            return configuration

    monkeypatch.setattr(whatsapp_configuration, "WhatsAppConfigurationDialog", FakeDialog)
    app = QApplication.instance() or QApplication([])
    page = whatsapp_configuration.WhatsAppConfigurationPage(user=user, current_user=user.username)

    page._configure()

    assert saved == [configuration]
    audit = AuditLog.get(AuditLog.action == "configurar")
    assert audit.module == "WhatsApp"
    assert audit.user == user.username
    assert audit.new_value["api_key"] == "protected"
    assert "rotated-key" not in str(audit.new_value)
    assert "rotated-key" not in (audit.observation or "")
    app.processEvents()

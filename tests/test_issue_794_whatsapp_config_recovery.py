"""Recuperacion de la configuracion de WhatsApp cuando la API key no se puede descifrar (#794)."""

from __future__ import annotations

import pytest

from app.models.system import AppParameter
from app.services.whatsapp_configuration_service import (
    CentralConfigurationError,
    WhatsAppCentralConfiguration,
    WhatsAppCentralConfigurationService,
)


def _save_config(monkeypatch):
    monkeypatch.setenv("DB_PASSWORD", "mysql-secret-for-tests")
    WhatsAppCentralConfigurationService.save(
        WhatsAppCentralConfiguration(
            api_url="https://gateway.example",
            api_key="clave-vieja",
            timeout_seconds=25,
            enabled=True,
        )
    )


def _corrupt_key():
    AppParameter.update(value="no-es-un-token-fernet").where(
        AppParameter.key == WhatsAppCentralConfigurationService.API_KEY_KEY
    ).execute()


def test_load_metadata_keeps_non_secret_configuration_when_key_is_corrupt(
    db, monkeypatch
):
    _save_config(monkeypatch)
    _corrupt_key()

    with pytest.raises(CentralConfigurationError):
        WhatsAppCentralConfigurationService.load()

    metadata = WhatsAppCentralConfigurationService.load_metadata()
    assert metadata is not None
    assert metadata.api_url == "https://gateway.example"
    assert metadata.api_key == ""
    assert metadata.timeout_seconds == 25.0
    assert metadata.enabled is True


def test_status_marks_pending_replacement_when_key_is_corrupt(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.whatsapp_configuration import WhatsAppConfigurationPage

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("DB_PASSWORD", "mysql-secret-for-tests")
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_wa_recovery", password_hash="x", profile=profile)
    _save_config(monkeypatch)
    _corrupt_key()
    monkeypatch.setattr(
        "app.ui.whatsapp_configuration.has_runtime_whatsapp_configuration",
        lambda: False,
    )

    page = WhatsAppConfigurationPage(user=user, current_user=user.username)
    app.processEvents()

    assert "pendiente de reemplazo" in page.status.text()
    assert "nueva clave" in page.status.text()


def test_configure_opens_dialog_when_key_cannot_be_decrypted(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog, QLabel

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.whatsapp_configuration import (
        WhatsAppConfigurationDialog,
        WhatsAppConfigurationPage,
    )

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_wa_configure", password_hash="x", profile=profile)

    metadata = WhatsAppCentralConfiguration(
        api_url="https://gateway.example",
        api_key="",
        timeout_seconds=25,
        enabled=True,
    )
    monkeypatch.setattr(
        WhatsAppCentralConfigurationService,
        "load",
        classmethod(lambda cls: (_ for _ in ()).throw(CentralConfigurationError("clave rota"))),
    )
    monkeypatch.setattr(
        WhatsAppCentralConfigurationService,
        "load_metadata",
        classmethod(lambda cls: metadata),
    )
    monkeypatch.setattr(
        "app.ui.whatsapp_configuration.has_runtime_whatsapp_configuration",
        lambda: False,
    )
    captured = {}

    def fake_exec(dialog_self):
        captured["dialog"] = dialog_self
        return QDialog.Rejected

    monkeypatch.setattr(WhatsAppConfigurationDialog, "exec_", fake_exec)

    page = WhatsAppConfigurationPage(user=user, current_user=user.username)
    page._configure()

    dialog = captured.get("dialog")
    assert dialog is not None
    warning = dialog.findChild(QLabel, "whatsappApiKeyRecoveryNotice")
    assert warning is not None
    assert "No se pudo recuperar la clave guardada" in warning.text()
    assert dialog.api_url.text() == "https://gateway.example"
    assert dialog.timeout.value() == 25
    assert dialog.api_key.placeholderText() == "Ingrese la nueva API key"
    assert dialog._current.api_key == ""


def test_dialog_keeps_url_and_does_not_reuse_empty_key(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.whatsapp_configuration import WhatsAppConfigurationDialog

    app = QApplication.instance() or QApplication([])
    current = WhatsAppCentralConfiguration(
        api_url="https://gateway.example",
        api_key="",
        timeout_seconds=20,
        enabled=True,
    )
    dialog = WhatsAppConfigurationDialog(current=current, load_error="clave rota")
    app.processEvents()

    assert dialog.api_url.text() == "https://gateway.example"
    assert dialog.timeout.value() == 20
    assert dialog.configuration().api_key == ""
    with pytest.raises(ValueError, match="API key"):
        dialog.configuration().validate()

"""El flag de envio automatico es central, no por puesto (#706)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _sin_env_real(monkeypatch, tmp_path):
    monkeypatch.setenv("FEMAG_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.delenv("FEMAG_PRESUPUESTOS_AUTOENVIO", raising=False)


def test_sin_configuracion_ni_env_esta_apagado(db, monkeypatch, tmp_path):
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )

    _sin_env_real(monkeypatch, tmp_path)
    assert BudgetAutoSendConfigurationService.load() is None
    assert BudgetAutoSendConfigurationService.habilitado() is False


def test_el_env_sigue_funcionando_como_respaldo(db, monkeypatch, tmp_path):
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_PRESUPUESTOS_AUTOENVIO", "1")
    assert BudgetAutoSendConfigurationService.habilitado() is True


def test_el_valor_central_manda_sobre_el_env(db, monkeypatch, tmp_path):
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_PRESUPUESTOS_AUTOENVIO", "1")
    BudgetAutoSendConfigurationService.save(False)
    assert BudgetAutoSendConfigurationService.load() is False
    assert BudgetAutoSendConfigurationService.habilitado() is False

    BudgetAutoSendConfigurationService.clear()
    monkeypatch.setenv("FEMAG_PRESUPUESTOS_AUTOENVIO", "0")
    BudgetAutoSendConfigurationService.save(True)
    assert BudgetAutoSendConfigurationService.habilitado() is True


def test_el_servicio_de_envio_usa_la_configuracion_central(db, monkeypatch, tmp_path):
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )
    from app.services.budget_auto_send_service import autoenvio_habilitado

    _sin_env_real(monkeypatch, tmp_path)
    assert autoenvio_habilitado() is False
    BudgetAutoSendConfigurationService.save(True)
    assert autoenvio_habilitado() is True


def _admin(username="admin_706_config"):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    perfil = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=perfil, active=True)


def test_la_pantalla_de_parametros_guarda_el_flag_central(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QCheckBox, QPushButton

    from app.models.audit import AuditLog
    from app.models.system import AppParameter
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )
    from app.ui.budget_auto_send_configuration import (
        BudgetAutoSendConfigurationPage,
    )

    app = QApplication.instance() or QApplication([])
    class _SilentBox:
        @staticmethod
        def information(*_args, **_kwargs):
            return None

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.ui.budget_auto_send_configuration.QMessageBox", _SilentBox
    )
    usuario = _admin()
    page = BudgetAutoSendConfigurationPage(
        user=usuario, current_user=usuario.username
    )
    app.processEvents()

    check = page.findChild(QCheckBox, "budgetAutoSendEnabledCheck")
    assert check is not None
    assert check.isChecked() is False

    check.setChecked(True)
    page.findChild(QPushButton, "budgetAutoSendSaveButton").click()
    app.processEvents()

    assert BudgetAutoSendConfigurationService.load() is True
    assert AppParameter.get(
        AppParameter.key == BudgetAutoSendConfigurationService.PARAMETER_KEY
    ).value == "1"
    assert AuditLog.select().where(
        AuditLog.record_ref == "envio automatico de presupuestos"
    ).exists()

    page.findChild(QPushButton, "budgetAutoSendClearButton").click()
    app.processEvents()
    assert BudgetAutoSendConfigurationService.load() is None


def test_quitar_la_configuracion_central_audita_el_valor_que_tenia(db, monkeypatch):
    """Al volver a la configuracion del puesto, la auditoria registra el valor
    central que se borra, sea habilitado o deshabilitado."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.audit import AuditLog
    from app.services.budget_auto_send_configuration_service import (
        BudgetAutoSendConfigurationService,
    )
    from app.ui.budget_auto_send_configuration import (
        BudgetAutoSendConfigurationPage,
    )

    app = QApplication.instance() or QApplication([])

    class _SilentBox:
        @staticmethod
        def information(*_args, **_kwargs):
            return None

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.ui.budget_auto_send_configuration.QMessageBox", _SilentBox
    )
    usuario = _admin("admin_706_clear_audit")
    BudgetAutoSendConfigurationService.save(False)
    page = BudgetAutoSendConfigurationPage(
        user=usuario, current_user=usuario.username
    )
    page.findChild(QPushButton, "budgetAutoSendClearButton").click()
    app.processEvents()

    assert BudgetAutoSendConfigurationService.load() is None
    registro = (
        AuditLog.select()
        .where(AuditLog.record_ref == "envio automatico de presupuestos")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert registro.old_value == {"habilitado": False}
    assert registro.new_value == {"habilitado": None}


def test_la_pantalla_esta_en_parametros(db):
    from PyQt5.QtWidgets import QApplication, QTabWidget

    from app.ui.parameters_page import ParametersPage

    app = QApplication.instance() or QApplication([])
    usuario = _admin("admin_706_config_tab")
    page = ParametersPage(user=usuario, current_user=usuario.username)
    tabs = page.findChild(QTabWidget, "parametersTabs")
    labels = [tabs.tabText(index) for index in range(tabs.count())]
    assert "Presupuestos" in labels
    indice = labels.index("Presupuestos")
    assert (
        tabs.widget(indice).objectName() == "budgetAutoSendConfigurationPage"
    )

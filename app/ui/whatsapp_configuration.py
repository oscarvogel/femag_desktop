from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config.secure_credentials import (
    RuntimeWhatsAppConfiguration,
    SecureConfigurationError,
    has_runtime_whatsapp_configuration,
    load_runtime_whatsapp_configuration,
    save_runtime_whatsapp_configuration,
)
from app.services.audit_service import AuditService
from app.services.permission_service import PermissionService


class WhatsAppConfigurationDialog(QDialog):
    def __init__(self, *, current: RuntimeWhatsAppConfiguration | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("whatsappConfigurationDialog")
        self.setWindowTitle("Configurar WhatsApp")
        self.setMinimumWidth(500)
        self._current = current

        intro = QLabel(
            "La API key se guarda cifrada con Windows para este usuario y nunca se muestra. "
            "Deje la clave vacía para conservar la que ya está guardada."
        )
        intro.setWordWrap(True)
        self.enabled = QCheckBox("Habilitar envío de extractos por WhatsApp")
        self.enabled.setChecked(current.enabled if current else False)
        self.api_url = QLineEdit(current.api_url if current else "")
        self.api_url.setPlaceholderText("https://gateway.ejemplo")
        self.instance_id = QLineEdit(current.instance_id if current else "default")
        self.api_key = QLineEdit()
        self.api_key.setObjectName("whatsappApiKeyInput")
        self.api_key.setEchoMode(QLineEdit.Password)
        if current:
            self.api_key.setPlaceholderText("Clave configurada; escribir sólo para reemplazarla")
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 120)
        self.timeout.setValue(int(current.timeout_seconds) if current else 15)
        self.timeout.setSuffix(" segundos")

        form = QFormLayout()
        form.addRow("", self.enabled)
        form.addRow("URL del gateway:", self.api_url)
        form.addRow("Instancia:", self.instance_id)
        form.addRow("API key:", self.api_key)
        form.addRow("Tiempo de espera:", self.timeout)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar configuración")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def configuration(self) -> RuntimeWhatsAppConfiguration:
        api_key = self.api_key.text()
        if not api_key and self._current is not None:
            api_key = self._current.api_key
        return RuntimeWhatsAppConfiguration(
            api_url=self.api_url.text(),
            api_key=api_key,
            instance_id=self.instance_id.text(),
            timeout_seconds=self.timeout.value(),
            enabled=self.enabled.isChecked(),
        )

    def _validate_and_accept(self) -> None:
        try:
            self.configuration().validate()
        except ValueError as exc:
            QMessageBox.warning(self, "Configurar WhatsApp", str(exc))
            return
        self.accept()


class WhatsAppConfigurationPage(QWidget):
    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("whatsappConfigurationPage")
        self.user = user
        self.current_user = current_user

        title = QLabel("Configuración de WhatsApp")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Esta configuración es local al usuario de Windows. La API key se protege con DPAPI."
        )
        subtitle.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("whatsappConfigurationStatus")
        self.configure_button = QPushButton("Configurar WhatsApp")
        self.configure_button.setObjectName("configureWhatsAppButton")
        self.configure_button.clicked.connect(self._configure)

        card = QFrame()
        card.setObjectName("whatsappConfigurationCard")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.status)
        card_layout.addWidget(self.configure_button, 0)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(card)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        allowed = PermissionService().has_permission(self.user, "Sistema", "configurar", "Parámetros")
        self.configure_button.setEnabled(allowed)
        if not allowed:
            self.configure_button.setToolTip("No tiene permiso para configurar WhatsApp.")
        try:
            configuration = load_runtime_whatsapp_configuration()
        except SecureConfigurationError:
            self.status.setText("WhatsApp no está configurado en este puesto.")
            return
        state = "habilitado" if configuration.enabled else "deshabilitado"
        self.status.setText(
            f"WhatsApp está {state}. Instancia: {configuration.instance_id}. "
            "API key configurada y protegida."
        )

    def _configure(self) -> None:
        if not PermissionService().has_permission(self.user, "Sistema", "configurar", "Parámetros"):
            QMessageBox.warning(self, "Configurar WhatsApp", "No tiene permiso para esta acción.")
            return
        current = None
        if has_runtime_whatsapp_configuration():
            try:
                current = load_runtime_whatsapp_configuration()
            except SecureConfigurationError as exc:
                QMessageBox.warning(self, "Configurar WhatsApp", str(exc))
                return
        dialog = WhatsAppConfigurationDialog(current=current, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        configuration = dialog.configuration()
        try:
            save_runtime_whatsapp_configuration(configuration)
        except (SecureConfigurationError, ValueError) as exc:
            QMessageBox.critical(self, "Configurar WhatsApp", str(exc))
            return
        AuditService().record(
            user=self.current_user,
            module="WhatsApp",
            action="configurar",
            record_ref="configuración local",
            old_value=_audit_value(current),
            new_value=_audit_value(configuration),
            observation="Configuración local de WhatsApp actualizada; API key protegida y omitida.",
        )
        self.refresh()
        QMessageBox.information(self, "Configurar WhatsApp", "La configuración se guardó correctamente.")


def _audit_value(configuration: RuntimeWhatsAppConfiguration | None) -> dict | None:
    if configuration is None:
        return None
    return {
        "enabled": configuration.enabled,
        "api_url": configuration.api_url,
        "instance_id": configuration.instance_id,
        "timeout_seconds": configuration.timeout_seconds,
        "api_key": "protected",
    }

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.secure_credentials import (
    SecureConfigurationError,
    has_runtime_whatsapp_configuration,
    load_runtime_whatsapp_configuration,
)
from app.models.security import User
from app.services.audit_service import AuditService
from app.services.permission_service import PermissionService
from app.services.whatsapp_api_client import WhatsAppApiClient, WhatsAppApiConfig, WhatsAppApiError
from app.services.whatsapp_configuration_service import (
    CentralConfigurationError,
    WhatsAppCentralConfiguration,
    WhatsAppCentralConfigurationService,
)


class WhatsAppConfigurationDialog(QDialog):
    def __init__(self, *, current: WhatsAppCentralConfiguration | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("whatsappConfigurationDialog")
        self.setWindowTitle("Configurar WhatsApp")
        self.setMinimumWidth(520)
        self._current = current

        intro = QLabel(
            "La configuración se guarda en la base MySQL y queda disponible para todos los puestos. "
            "La API key se almacena cifrada y nunca se muestra completa después de guardarla."
        )
        intro.setWordWrap(True)
        self.enabled = QCheckBox("Habilitar envíos por WhatsApp")
        self.enabled.setChecked(current.enabled if current else False)
        self.api_url = QLineEdit(current.api_url if current else "")
        self.api_url.setPlaceholderText("https://whatsapp.vogelconsultoria.com.ar")
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

    def configuration(self) -> WhatsAppCentralConfiguration:
        api_key = self.api_key.text()
        if not api_key and self._current is not None:
            api_key = self._current.api_key
        return WhatsAppCentralConfiguration(
            api_url=self.api_url.text(),
            api_key=api_key,
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
        self._instances: list[dict] = []

        title = QLabel("Configuración de WhatsApp")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Configuración central para todos los puestos. Cada usuario puede tener su propia "
            "instancia de Vogel WhatsApp API."
        )
        subtitle.setWordWrap(True)

        self.status = QLabel()
        self.status.setObjectName("whatsappConfigurationStatus")
        self.configure_button = QPushButton("Configurar conexión")
        self.configure_button.setObjectName("configureWhatsAppButton")
        self.configure_button.clicked.connect(self._configure)
        self.refresh_instances_button = QPushButton("Cargar instancias disponibles")
        self.refresh_instances_button.setObjectName("refreshWhatsAppInstancesButton")
        self.refresh_instances_button.clicked.connect(self._load_instances)

        card = QFrame()
        card.setObjectName("whatsappConfigurationCard")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addWidget(self.configure_button)
        buttons.addWidget(self.refresh_instances_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)

        users_title = QLabel("Instancia por usuario")
        users_title.setObjectName("whatsappUsersTitle")
        users_help = QLabel(
            "Seleccione desde qué WhatsApp enviará cada usuario. Un usuario sin instancia "
            "puede usar FEMAG normalmente, pero no podrá enviar por WhatsApp."
        )
        users_help.setWordWrap(True)

        self.users_table = QTableWidget(0, 3)
        self.users_table.setObjectName("whatsappUsersTable")
        self.users_table.setHorizontalHeaderLabels(["Usuario", "Nombre", "Instancia WhatsApp"])
        self.users_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.users_table.horizontalHeader().setStretchLastSection(True)

        self.save_users_button = QPushButton("Guardar asignaciones")
        self.save_users_button.setObjectName("saveWhatsAppUserAssignmentsButton")
        self.save_users_button.clicked.connect(self._save_user_assignments)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(card)
        layout.addSpacing(14)
        layout.addWidget(users_title)
        layout.addWidget(users_help)
        layout.addWidget(self.users_table, 1)
        layout.addWidget(self.save_users_button, 0)
        self.refresh()

    def _allowed(self) -> bool:
        return PermissionService().has_permission(
            self.user, "Sistema", "configurar", "Parámetros"
        )

    def _current_configuration(self) -> WhatsAppCentralConfiguration | None:
        return WhatsAppCentralConfigurationService.load()

    def refresh(self) -> None:
        allowed = self._allowed()
        for button in (
            self.configure_button,
            self.refresh_instances_button,
            self.save_users_button,
        ):
            button.setEnabled(allowed)
        if not allowed:
            self.configure_button.setToolTip("No tiene permiso para configurar WhatsApp.")

        try:
            configuration = self._current_configuration()
        except (CentralConfigurationError, ValueError) as exc:
            self.status.setText(f"Configuración central inválida: {exc}")
            configuration = None

        if configuration is None:
            if has_runtime_whatsapp_configuration():
                self.status.setText(
                    "Aún no hay configuración central. Se detectó una configuración local anterior; "
                    "abra Configurar conexión y guárdela para migrarla a MySQL."
                )
            else:
                self.status.setText("WhatsApp todavía no está configurado en la base central.")
        else:
            state = "habilitado" if configuration.enabled else "deshabilitado"
            self.status.setText(
                f"WhatsApp está {state}. Gateway: {configuration.api_url}. "
                "API key central configurada y protegida."
            )
        self._refresh_users_table()

    def _legacy_configuration(self) -> WhatsAppCentralConfiguration | None:
        if not has_runtime_whatsapp_configuration():
            return None
        try:
            old = load_runtime_whatsapp_configuration()
        except SecureConfigurationError:
            return None
        return WhatsAppCentralConfiguration(
            api_url=old.api_url,
            api_key=old.api_key,
            timeout_seconds=old.timeout_seconds,
            enabled=old.enabled,
        )

    def _configure(self) -> None:
        if not self._allowed():
            QMessageBox.warning(self, "Configurar WhatsApp", "No tiene permiso para esta acción.")
            return
        try:
            current = self._current_configuration()
        except (CentralConfigurationError, ValueError) as exc:
            QMessageBox.warning(self, "Configurar WhatsApp", str(exc))
            return
        current = current or self._legacy_configuration()
        dialog = WhatsAppConfigurationDialog(current=current, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        configuration = dialog.configuration()
        try:
            WhatsAppCentralConfigurationService.save(configuration)
        except (CentralConfigurationError, ValueError) as exc:
            QMessageBox.critical(self, "Configurar WhatsApp", str(exc))
            return
        AuditService().record(
            user=self.current_user,
            module="WhatsApp",
            action="configurar",
            record_ref="configuración central",
            old_value=_audit_value(current),
            new_value=_audit_value(configuration),
            observation="Configuración central de WhatsApp actualizada; API key protegida y omitida.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Configurar WhatsApp",
            "La configuración central se guardó correctamente.",
        )

    def _load_instances(self) -> None:
        if not self._allowed():
            return
        try:
            configuration = self._current_configuration()
            if configuration is None:
                raise WhatsAppApiError("Primero guarde la configuración central de WhatsApp.")
            client = WhatsAppApiClient(
                WhatsAppApiConfig(
                    base_url=configuration.api_url,
                    api_key=configuration.api_key,
                    timeout_seconds=configuration.timeout_seconds,
                    enabled=configuration.enabled,
                )
            )
            self._instances = client.list_instances()
        except (CentralConfigurationError, WhatsAppApiError, ValueError) as exc:
            QMessageBox.warning(self, "Instancias WhatsApp", str(exc))
            return
        self._refresh_users_table()
        QMessageBox.information(
            self,
            "Instancias WhatsApp",
            f"Se cargaron {len(self._instances)} instancia(s) autorizada(s).",
        )

    def _refresh_users_table(self) -> None:
        users = list(User.select().order_by(User.username))
        self.users_table.setRowCount(len(users))
        available_ids = [
            str(item.get("id") or "").strip()
            for item in self._instances
            if str(item.get("id") or "").strip()
        ]
        for row, user in enumerate(users):
            username_item = QTableWidgetItem(user.username)
            username_item.setData(0x0100, user.id)
            self.users_table.setItem(row, 0, username_item)
            self.users_table.setItem(row, 1, QTableWidgetItem(user.display_name or "-"))
            combo = QComboBox()
            combo.setObjectName(f"whatsappInstanceCombo_{user.id}")
            combo.addItem("Sin instancia", None)
            current = (user.whatsapp_instance_id or "").strip()
            choices = list(available_ids)
            if current and current not in choices:
                choices.append(current)
            for instance_id in choices:
                status = next(
                    (
                        str(item.get("status") or "").strip()
                        for item in self._instances
                        if str(item.get("id") or "").strip() == instance_id
                    ),
                    "",
                )
                label = f"{instance_id} ({status})" if status else instance_id
                combo.addItem(label, instance_id)
            combo.setCurrentIndex(max(0, combo.findData(current or None)))
            self.users_table.setCellWidget(row, 2, combo)

    def _save_user_assignments(self) -> None:
        if not self._allowed():
            QMessageBox.warning(self, "WhatsApp", "No tiene permiso para esta acción.")
            return
        changed = 0
        for row in range(self.users_table.rowCount()):
            item = self.users_table.item(row, 0)
            combo = self.users_table.cellWidget(row, 2)
            if item is None or combo is None:
                continue
            user = User.get_by_id(item.data(0x0100))
            new_instance = combo.currentData() or None
            old_instance = user.whatsapp_instance_id
            if old_instance == new_instance:
                continue
            user.whatsapp_instance_id = new_instance
            user.save(only=[User.whatsapp_instance_id])
            AuditService().record(
                user=self.current_user,
                module="WhatsApp",
                action="asignar instancia usuario",
                record_ref=f"User:{user.id}",
                old_value={"whatsapp_instance_id": old_instance},
                new_value={"whatsapp_instance_id": new_instance},
            )
            changed += 1
        QMessageBox.information(
            self,
            "WhatsApp",
            f"Asignaciones guardadas: {changed} cambio(s).",
        )
        self._refresh_users_table()


def _audit_value(configuration: WhatsAppCentralConfiguration | None) -> dict | None:
    if configuration is None:
        return None
    return {
        "enabled": configuration.enabled,
        "api_url": configuration.api_url,
        "timeout_seconds": configuration.timeout_seconds,
        "api_key": "protected",
    }

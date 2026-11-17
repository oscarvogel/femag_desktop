"""Configuracion central del envio automatico de presupuestos (#706).

Es una decision del sistema, no del puesto: va en ``Parametros`` y la
comparten todos los equipos. Antes era una variable del ``.env`` local, que con
muchos puestos no se puede administrar.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.audit_service import AuditService
from app.services.budget_auto_send_configuration_service import (
    BudgetAutoSendConfigurationService,
)
from app.services.permission_service import PermissionService


class BudgetAutoSendConfigurationPage(QWidget):
    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("budgetAutoSendConfigurationPage")
        self.user = user
        self.current_user = current_user

        title = QLabel("Envio automatico de presupuestos")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Al emitir una orden de carga, enviar el presupuesto a cada cliente por "
            "WhatsApp y correo. Es una configuracion central: la comparten todos los "
            "puestos."
        )
        subtitle.setWordWrap(True)

        self.status = QLabel()
        self.status.setObjectName("budgetAutoSendConfigurationStatus")
        self.status.setWordWrap(True)

        self.enabled_check = QCheckBox(
            "Enviar los presupuestos automaticamente al emitir una orden de carga"
        )
        self.enabled_check.setObjectName("budgetAutoSendEnabledCheck")

        self.save_button = QPushButton("Guardar")
        self.save_button.setObjectName("budgetAutoSendSaveButton")
        self.save_button.clicked.connect(self._save)
        self.clear_button = QPushButton("Usar la configuracion del puesto")
        self.clear_button.setObjectName("budgetAutoSendClearButton")
        self.clear_button.clicked.connect(self._clear)

        card = QFrame()
        card.setObjectName("budgetAutoSendConfigurationCard")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.status)
        card_layout.addWidget(self.enabled_check)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)

        help_text = QLabel(
            "Cada presupuesto tiene un solo destinatario: el vendedor del cliente si "
            "lo tiene, si no el cliente. Si falta el WhatsApp o el correo, ese canal "
            "queda omitido con el motivo y la orden se emite igual. El correo "
            "empezara a salir cuando haya direcciones cargadas."
        )
        help_text.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(card)
        layout.addWidget(help_text)
        layout.addStretch(1)

        self.refresh()

    def _allowed(self) -> bool:
        return PermissionService().has_permission(
            self.user, "Sistema", "configurar", "Parámetros"
        )

    def refresh(self) -> None:
        allowed = self._allowed()
        self.enabled_check.setEnabled(allowed)
        self.save_button.setEnabled(allowed)
        self.clear_button.setEnabled(allowed)
        if not allowed:
            self.save_button.setToolTip(
                "No tiene permiso para configurar el envio automatico."
            )

        central = BudgetAutoSendConfigurationService.load()
        self.enabled_check.setChecked(
            BudgetAutoSendConfigurationService.habilitado()
        )
        if central is None:
            estado = "habilitado" if self.enabled_check.isChecked() else "deshabilitado"
            self.status.setText(
                "Sin configuracion central. Hoy manda la configuracion del puesto: "
                f"{estado}."
            )
        else:
            estado = "habilitado" if central else "deshabilitado"
            self.status.setText(
                f"Configuracion central: envio automatico {estado}. "
                "Se aplica a todos los puestos."
            )

    def _save(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Envio automatico de presupuestos", "No tiene permiso para esta accion."
            )
            return
        previous = BudgetAutoSendConfigurationService.load()
        actual = BudgetAutoSendConfigurationService.save(
            self.enabled_check.isChecked()
        )
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="envio automatico de presupuestos",
            old_value={"habilitado": previous},
            new_value={"habilitado": actual},
            observation="Envio automatico de presupuestos al emitir una orden.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Envio automatico de presupuestos",
            "La configuracion se guardo para todos los puestos.",
        )

    def _clear(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Envio automatico de presupuestos", "No tiene permiso para esta accion."
            )
            return
        if BudgetAutoSendConfigurationService.load() is None:
            self.refresh()
            return
        BudgetAutoSendConfigurationService.clear()
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="envio automatico de presupuestos",
            old_value={"habilitado": True},
            new_value={"habilitado": None},
            observation="Se quito la configuracion central; vuelve a mandar el puesto.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Envio automatico de presupuestos",
            "Se quito la configuracion central. Vuelve a mandar la configuracion del puesto.",
        )


__all__ = ["BudgetAutoSendConfigurationPage"]

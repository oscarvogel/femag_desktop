from __future__ import annotations

from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.audit_service import AuditService
from app.services.permission_service import PermissionService
from app.services.webapp_configuration_service import (
    WebappConfigurationError,
    WebappConfigurationService,
)


class WebappConfigurationPage(QWidget):
    """URL base del servidor web que abre las ordenes desde el celular."""

    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.setObjectName("webappConfigurationPage")
        self.user = user
        self.current_user = current_user

        title = QLabel("Servidor web")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Direccion del servidor de la webapp que se imprime en el QR de las ordenes "
            "de carga. Es una configuracion central: la comparten todos los puestos."
        )
        subtitle.setWordWrap(True)

        self.status = QLabel()
        self.status.setObjectName("webappConfigurationStatus")

        self.url_input = QLineEdit()
        self.url_input.setObjectName("webappPublicUrlInput")
        self.url_input.setPlaceholderText("http://192.168.0.111:8000")
        self.url_input.returnPressed.connect(self._save)

        help_text = QLabel(
            "Use la direccion que el celular puede abrir dentro de la red de la fabrica, "
            "por ejemplo http://192.168.0.111:8000. Se acepta http:// o https://, con "
            "puerto opcional y sin ruta. HTTP alcanza para la LAN del piloto; no exponga "
            "ese puerto a Internet. Si no hay URL configurada, las ordenes se imprimen "
            "sin QR para no imprimir un acceso que no funciona."
        )
        help_text.setWordWrap(True)

        self.save_button = QPushButton("Guardar URL")
        self.save_button.setObjectName("webappPublicUrlSaveButton")
        self.save_button.clicked.connect(self._save)
        self.clear_button = QPushButton("Quitar URL")
        self.clear_button.setObjectName("webappPublicUrlClearButton")
        self.clear_button.clicked.connect(self._clear)

        card = QFrame()
        card.setObjectName("webappConfigurationCard")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(self.status)
        card_layout.addWidget(QLabel("URL base:"))
        card_layout.addWidget(self.url_input)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)

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
        self.url_input.setEnabled(allowed)
        self.save_button.setEnabled(allowed)
        self.clear_button.setEnabled(allowed)
        if not allowed:
            self.save_button.setToolTip("No tiene permiso para configurar el servidor web.")

        configured = WebappConfigurationService.public_url()
        self.url_input.setText(configured)
        if configured:
            self.status.setText(
                f"Servidor web configurado: {configured}. El QR de las ordenes abre "
                f"{configured}/orden/<token>."
            )
        else:
            self.status.setText(
                "El servidor web todavia no esta configurado. Las ordenes se imprimen "
                "sin QR hasta que se guarde una URL."
            )

    def _save(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Servidor web", "No tiene permiso para esta accion."
            )
            return
        previous = WebappConfigurationService.public_url()
        try:
            saved = WebappConfigurationService.save_public_url(self.url_input.text())
        except (WebappConfigurationError, ValueError) as exc:
            QMessageBox.warning(self, "Servidor web", str(exc))
            return
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="servidor web",
            old_value={"public_url": previous or None},
            new_value={"public_url": saved or None},
            observation="URL base del servidor web configurada para el QR de ordenes.",
        )
        self.refresh()
        QMessageBox.information(
            self,
            "Servidor web",
            "La URL se guardo. Las proximas ordenes se imprimen con el QR nuevo.",
        )

    def _clear(self) -> None:
        if not self._allowed():
            QMessageBox.warning(
                self, "Servidor web", "No tiene permiso para esta accion."
            )
            return
        previous = WebappConfigurationService.public_url()
        if not previous:
            self.refresh()
            return
        answer = QMessageBox.question(
            self,
            "Servidor web",
            "Se quita la URL y las ordenes se imprimen sin QR. ¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        WebappConfigurationService.save_public_url("")
        AuditService().record(
            user=self.current_user,
            module="Sistema",
            action="configurar",
            record_ref="servidor web",
            old_value={"public_url": previous},
            new_value={"public_url": None},
            observation="URL base del servidor web quitada.",
        )
        self.refresh()

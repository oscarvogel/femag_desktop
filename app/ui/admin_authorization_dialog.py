from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.models.security import User
from app.services.auth_service import AuthService


class AdminAuthorizationDialog(QDialog):
    def __init__(
        self,
        *,
        auth_service: AuthService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Autorizar anulación de pago")
        self.setModal(True)
        self.resize(420, 230)
        self.auth_service = auth_service or AuthService()
        self._authorized_user: User | None = None

        layout = QVBoxLayout(self)
        message = QLabel(
            "Ingrese las credenciales de un administrador y el motivo de la anulación."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        form = QFormLayout()
        self.username_input = QLineEdit()
        self.username_input.setObjectName("adminAuthorizationUsernameInput")
        form.addRow("Usuario administrador", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("adminAuthorizationPasswordInput")
        self.password_input.setEchoMode(QLineEdit.Password)
        form.addRow("Clave", self.password_input)

        self.reason_input = QLineEdit()
        self.reason_input.setObjectName("adminAuthorizationReasonInput")
        self.reason_input.setPlaceholderText("Motivo de la anulación")
        form.addRow("Motivo", self.reason_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("adminAuthorizationAcceptButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("adminAuthorizationCancelButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def authorized_user(self) -> User | None:
        return self._authorized_user

    def reason(self) -> str | None:
        return self.reason_input.text().strip() or None

    def _on_accept(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            QMessageBox.warning(
                self,
                "Autorización",
                "Ingrese usuario y clave de administrador.",
            )
            return
        user = self.auth_service.authorize_administrator(username, password)
        if user is None:
            QMessageBox.warning(
                self,
                "Autorización",
                "Las credenciales no corresponden a un administrador activo.",
            )
            return
        self._authorized_user = user
        self.accept()

from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout

from app.models.security import User
from app.services.managerial_access_service import ManagerialAccessService


class ManagerialAuthorizationDialog(QDialog):
    def __init__(
        self,
        *,
        requested_by: User,
        access_service: ManagerialAccessService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Autorizar acceso al Dashboard Gerencial")
        self.setModal(True)
        self.resize(440, 210)
        self.requested_by = requested_by
        self.access_service = access_service or ManagerialAccessService()
        self._authorized_user: User | None = None

        layout = QVBoxLayout(self)
        message = QLabel(
            "Ingrese las credenciales de un usuario autorizado para consultar información gerencial."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        form = QFormLayout()
        self.username_input = QLineEdit()
        self.username_input.setObjectName("managerialAuthorizationUsernameInput")
        form.addRow("Usuario autorizador", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("managerialAuthorizationPasswordInput")
        self.password_input.setEchoMode(QLineEdit.Password)
        form.addRow("Clave", self.password_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("managerialAuthorizationAcceptButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("managerialAuthorizationCancelButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def authorized_user(self) -> User | None:
        return self._authorized_user

    def _on_accept(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            QMessageBox.warning(self, "Autorización", "Ingrese usuario y clave.")
            return
        user = self.access_service.authorize(
            username,
            password,
            requested_by=self.requested_by,
        )
        if user is None:
            QMessageBox.warning(
                self,
                "Autorización",
                "Las credenciales no corresponden a un usuario con acceso gerencial.",
            )
            return
        self._authorized_user = user
        self.accept()

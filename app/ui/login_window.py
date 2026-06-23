from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.auth_service import AuthService


class LoginWindow(QDialog):
    def __init__(self, auth_service: AuthService | None = None):
        super().__init__()
        self.auth_service = auth_service or AuthService()
        self.user = None
        self.setWindowTitle("FEMAG Desktop - Ingreso")
        self.setMinimumSize(420, 260)

        title = QLabel("FEMAG Desktop")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignCenter)

        subtitle = QLabel("Ingresá con un usuario demo para revisar la operatoria.")
        subtitle.setAlignment(Qt.AlignCenter)

        self.username = QComboBox()
        self.username.setEditable(True)
        self.username.addItems(["secretaria", "admin", "administracion", "consulta"])
        self.username.setToolTip("Usuarios demo: secretaria, admin, administracion, consulta")

        self.password = QLineEdit("demo")
        self.password.setEchoMode(QLineEdit.Password)

        self.message = QLabel("")
        self.message.setObjectName("loginMessage")
        self.message.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Usuario", self.username)
        form.addRow("Clave", self.password)

        login_button = QPushButton("Ingresar")
        login_button.setObjectName("primaryButton")
        login_button.clicked.connect(self.try_login)
        cancel_button = QPushButton("Cerrar")
        cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_button)
        buttons.addWidget(login_button)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addStretch()
        layout.addLayout(buttons)
        self._apply_style()

    def try_login(self) -> None:
        user = self.auth_service.authenticate(self.username.currentText().strip(), self.password.text())
        if not user:
            self.message.setText("Usuario o clave incorrectos. Revisá los datos e intentá nuevamente.")
            return
        self.user = user
        self.accept()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #f6f7f9; font-size: 14px; }
            QLabel#loginTitle { font-size: 24px; font-weight: 700; color: #1f2933; }
            QLabel#loginMessage { color: #b42318; min-height: 28px; }
            QLineEdit, QComboBox { padding: 8px; border: 1px solid #b8c0cc; border-radius: 4px; background: white; }
            QPushButton { padding: 8px 14px; border-radius: 4px; border: 1px solid #9aa4b2; background: #ffffff; }
            QPushButton#primaryButton { background: #1f6feb; color: white; border-color: #1f6feb; font-weight: 600; }
            """
        )

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from app.services.auth_service import AuthService


class LoginWindow(QDialog):
    def __init__(self, *, demo_mode: bool = False, parent=None):
        super().__init__(parent)
        self.authenticated_user = None
        self.demo_mode = demo_mode
        self.setWindowTitle("FEMAG Desktop - Inicio de sesion")
        self.setFixedSize(380, 260)
        self.setStyleSheet(self._STYLES)
        self._build()

    def _build(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        title = QLabel("FEMAG Desktop")
        title.setObjectName("loginTitle")
        layout.addWidget(title)

        subtitle = QLabel("Ingrese sus credenciales")
        subtitle.setObjectName("loginSubtitle")
        layout.addWidget(subtitle)

        if self.demo_mode:
            hint = QLabel("Modo demo: usuario 'demo', clave 'demo'")
            hint.setObjectName("loginHint")
            layout.addWidget(hint)

        self.username_input = QLineEdit()
        self.username_input.setObjectName("loginUsernameInput")
        self.username_input.setPlaceholderText("Usuario")
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("loginPasswordInput")
        self.password_input.setPlaceholderText("Contrasena")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        self.feedback = QLabel("")
        self.feedback.setObjectName("loginFeedback")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        if self.demo_mode:
            demo_fill = QPushButton("Completar demo")
            demo_fill.setObjectName("loginDemoFillButton")
            demo_fill.setProperty("secondary", True)
            demo_fill.clicked.connect(self._fill_demo)
            buttons.addWidget(demo_fill)

        buttons.addStretch()
        cancel_btn = QPushButton("Salir")
        cancel_btn.setObjectName("loginCancelButton")
        cancel_btn.setProperty("secondary", True)
        cancel_btn.clicked.connect(self.reject)
        login_btn = QPushButton("Ingresar")
        login_btn.setObjectName("loginSubmitButton")
        login_btn.setDefault(True)
        login_btn.clicked.connect(self._attempt_login)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(login_btn)
        layout.addLayout(buttons)

        self.setLayout(layout)

    def _fill_demo(self):
        self.username_input.setText("demo")
        self.password_input.setText("demo")

    def _attempt_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.feedback.setText("Ingrese usuario y contrasena.")
            return
        user = AuthService().authenticate(username, password)
        if user is None:
            self.feedback.setText("Usuario o contrasena incorrectos.")
            return
        self.authenticated_user = user
        self.accept()

    def show(self):
        return self.exec_()

    _STYLES = """
    QDialog { background: #f8fafc; }
    #loginTitle { font-size: 22px; font-weight: 700; color: #0f172a; }
    #loginSubtitle { color: #64748b; font-size: 13px; margin-bottom: 4px; }
    #loginHint { color: #0b6fdc; font-size: 12px; font-weight: 600; padding: 6px 10px;
                 background: #e8f1ff; border-radius: 4px; }
    QLineEdit { padding: 10px 12px; border: 1px solid #d9e1ec; border-radius: 6px;
                background: #ffffff; font-size: 14px; }
    QLineEdit:focus { border-color: #0b6fdc; }
    #loginFeedback { color: #b91c1c; font-size: 12px; min-height: 18px; }
    QPushButton { background: #0b6fdc; color: #ffffff; border: 0; border-radius: 6px;
                  padding: 9px 18px; font-weight: 600; font-size: 14px; min-width: 80px; }
    QPushButton[secondary="true"] { background: #ffffff; color: #334155;
                                    border: 1px solid #d9e1ec; }
    QPushButton:hover { opacity: 0.9; }
    """

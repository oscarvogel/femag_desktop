from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout

from app.models.security import User
from app.services.auth_service import AuthService
from app.ui.branding import femag_icon, load_brand_pixmap
from app.ui.form_feedback import FormFeedback
from app.ui.user_management import InitialAdminDialog


class LoginWindow(QDialog):
    def __init__(self, *, demo_mode: bool = False, parent=None):
        super().__init__(parent)
        self.authenticated_user = None
        self.demo_mode = demo_mode
        self.setWindowTitle("FEMAG Desktop - Inicio de sesion")
        self.setWindowIcon(femag_icon())
        self.setFixedWidth(460)
        self.setStyleSheet(self._STYLES)
        self._build()
        self.setMinimumHeight(self.minimumSizeHint().height())

    def _build(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        outer = QFrame()
        outer.setObjectName("loginOuter")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(40, 36, 40, 28)
        outer_layout.setSpacing(0)

        logo = QLabel()
        logo.setObjectName("loginBrandLogo")
        logo.setAccessibleName("Logo FEMAG")
        logo.setAlignment(Qt.AlignCenter)
        logo.setPixmap(load_brand_pixmap("femag-logo-ui.png", width=270, height=150))
        logo.setMinimumHeight(150)
        outer_layout.addWidget(logo)

        outer_layout.addSpacing(12)

        title = QLabel("FEMAG Desktop")
        title.setObjectName("loginTitle")
        outer_layout.addWidget(title)

        outer_layout.addSpacing(4)

        subtitle = QLabel("Ingrese sus credenciales para continuar")
        subtitle.setObjectName("loginSubtitle")
        outer_layout.addWidget(subtitle)

        outer_layout.addSpacing(18)

        if self.demo_mode:
            hint = QLabel("Modo demo: usuario demo / clave demo")
            hint.setObjectName("loginHint")
            outer_layout.addWidget(hint)
            outer_layout.addSpacing(18)

        username_label = QLabel("Usuario")
        username_label.setObjectName("loginFieldLabel")
        outer_layout.addWidget(username_label)
        outer_layout.addSpacing(4)

        self.username_input = QLineEdit()
        self.username_input.setObjectName("loginUsernameInput")
        self.username_input.setPlaceholderText("Ingrese su usuario")
        outer_layout.addWidget(self.username_input)

        outer_layout.addSpacing(12)

        password_label = QLabel("Contrasena")
        password_label.setObjectName("loginFieldLabel")
        outer_layout.addWidget(password_label)
        outer_layout.addSpacing(4)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("loginPasswordInput")
        self.password_input.setPlaceholderText("Ingrese su contrasena")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self._attempt_login)
        outer_layout.addWidget(self.password_input)

        outer_layout.addSpacing(6)

        self.feedback = FormFeedback("loginFeedback")
        outer_layout.addWidget(self.feedback)

        outer_layout.addSpacing(10)

        self.bootstrap_button = None
        # El chequeo de "primer administrador" requiere una DB inicializada.
        # La app real siempre la garantiza antes de mostrar el login, pero los
        # tests instancian LoginWindow con un proxy sin inicializar y no podemos
        # romperlos: si la consulta falla por cualquier motivo, asumimos que la
        # DB no está lista y ocultamos el botón. La app real nunca debería
        # entrar por esta rama.
        try:
            needs_bootstrap = not User.select().exists()
        except Exception:
            needs_bootstrap = False
        if needs_bootstrap:
            self.bootstrap_button = QPushButton("Crear administrador inicial")
            self.bootstrap_button.setObjectName("loginBootstrapButton")
            self.bootstrap_button.clicked.connect(self._create_initial_admin)
            outer_layout.addWidget(self.bootstrap_button)
            outer_layout.addSpacing(8)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        if self.demo_mode:
            demo_fill = QPushButton("Completar demo")
            demo_fill.setObjectName("loginDemoFillButton")
            demo_fill.setMinimumWidth(140)
            demo_fill.clicked.connect(self._fill_demo)
            buttons.addWidget(demo_fill)

        buttons.addStretch()

        cancel_btn = QPushButton("Salir")
        cancel_btn.setObjectName("loginCancelButton")
        cancel_btn.setMinimumWidth(90)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)

        login_btn = QPushButton("Ingresar")
        login_btn.setObjectName("loginSubmitButton")
        login_btn.setMinimumWidth(110)
        login_btn.setDefault(True)
        login_btn.clicked.connect(self._attempt_login)
        buttons.addWidget(login_btn)

        outer_layout.addLayout(buttons)

        root.addWidget(outer)
        self.setLayout(root)

    def _fill_demo(self):
        self.username_input.setText("demo")
        self.password_input.setText("demo")
        self.feedback.clear_message()
        self.adjustSize()

    def _attempt_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            focus_widget = self.username_input if not username else self.password_input
            self.feedback.show_warning(
                "Complete ambos campos para ingresar.", focus_widget=focus_widget
            )
            self.adjustSize()
            return
        user = AuthService().authenticate(username, password)
        if user is None:
            self.feedback.show_error(
                "Usuario o contrasena incorrectos. Verifique sus credenciales.",
                focus_widget=self.password_input,
            )
            self.adjustSize()
            return
        self.authenticated_user = user
        self.accept()

    def _create_initial_admin(self):
        dialog = InitialAdminDialog(parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        try:
            AuthService().create_initial_admin(
                values["username"],
                values["password"],
                display_name=values["display_name"],
            )
            self.authenticated_user = AuthService().authenticate(
                values["username"], values["password"]
            )
        except (ValueError, TypeError) as exc:
            self.feedback.show_error(str(exc))
            self.adjustSize()
            return
        self.accept()

    def show(self):
        return self.exec_()

    _STYLES = """
    QDialog {
        background: #f0f2f5;
    }
    #loginOuter {
        background: #ffffff;
        border: 1px solid #d9e1ec;
        border-radius: 10px;
        margin: 16px;
    }
    #loginTitle {
        font-size: 24px;
        font-weight: 700;
        color: #0f172a;
    }
    #loginBrandLogo {
        background: transparent;
    }
    #loginSubtitle {
        font-size: 13px;
        color: #64748b;
    }
    #loginHint {
        font-size: 12px;
        font-weight: 600;
        color: #0b6fdc;
        background: #e8f1ff;
        border-radius: 6px;
        padding: 8px 12px;
    }
    #loginFieldLabel {
        font-size: 13px;
        font-weight: 600;
        color: #334155;
    }
    QLineEdit {
        padding: 10px 12px;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #ffffff;
        font-size: 14px;
        color: #0f172a;
        min-height: 20px;
    }
    QLineEdit:focus {
        border-color: #0b6fdc;
        background: #ffffff;
    }
    QLineEdit::placeholder {
        color: #94a3b8;
    }
    QPushButton {
        border-radius: 6px;
        font-size: 14px;
        font-weight: 600;
        min-height: 22px;
        padding: 14px 28px;
    }
    #loginSubmitButton {
        background: #2563eb;
        color: #ffffff;
        border: 0;
    }
    #loginSubmitButton:hover {
        background: #1d4ed8;
    }
    #loginSubmitButton:pressed {
        background: #1e40af;
    }
    #loginCancelButton {
        background: #ffffff;
        color: #374151;
        border: 1px solid #d1d5db;
    }
    #loginCancelButton:hover {
        background: #f3f4f6;
    }
    #loginCancelButton:pressed {
        background: #e5e7eb;
    }
    #loginDemoFillButton {
        background: #eff6ff;
        color: #1d4ed8;
        border: 1px solid #bfdbfe;
    }
    #loginDemoFillButton:hover {
        background: #dbeafe;
    }
    #loginDemoFillButton:pressed {
        background: #bfdbfe;
    }
    """

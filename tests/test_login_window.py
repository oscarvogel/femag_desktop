import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_invalid_login_stays_open_and_only_explicit_exit_rejects(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.ui.login_window import LoginWindow

    app = QApplication.instance() or QApplication([])
    dialog = LoginWindow(demo_mode=False)
    rejected = []
    dialog.rejected.connect(lambda: rejected.append(True))

    monkeypatch.setattr(
        "app.ui.login_window.AuthService.authenticate",
        lambda _self, _username, _password: None,
    )

    dialog.username_input.setText("usuario_incorrecto")
    dialog.password_input.setText("clave_incorrecta")
    dialog._attempt_login()
    app.processEvents()

    assert dialog.authenticated_user is None
    assert "Usuario o contraseña incorrectos" in dialog.feedback.text()
    assert rejected == []

    dialog.reject()
    app.processEvents()
    assert rejected == []

    dialog._cancel_login()
    app.processEvents()
    assert rejected == [True]

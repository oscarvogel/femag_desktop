from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _fake_desktop_environment(monkeypatch, events, *, session_closed: bool = False):
    """Reemplaza todo lo que ``run_desktop_app`` toca para observar el teardown."""
    import app.ui.desktop_app as desktop_app

    class FakeApp:
        @staticmethod
        def instance():
            return fake_app

        def setWindowIcon(self, icon):
            events.append("app.setWindowIcon")

        def setStyleSheet(self, stylesheet):
            events.append("app.setStyleSheet")

        def exec_(self):
            events.append("app.exec_")
            return 0

    fake_app = FakeApp()

    class FakeQApplication:
        @staticmethod
        def instance():
            return fake_app

        @staticmethod
        def sendPostedEvents(receiver, event_type):
            events.append(("app.sendPostedEvents", event_type))

    class FakeLoginWindow:
        def __init__(self, *, demo_mode=False, parent=None):
            self.authenticated_user = "demo"

        def show(self):
            events.append("login.show")
            return 1  # QDialog.Accepted

    class FakeDesktopWindow:
        def __init__(self, *, user, demo_mode):
            self.user = user
            self.session_closed = session_closed

        def show(self):
            events.append("window.show")

        def deleteLater(self):
            events.append("window.deleteLater")

    class FakePermissionService:
        def seed_defaults(self):
            return None

    monkeypatch.setattr(desktop_app, "QApplication", FakeQApplication)
    monkeypatch.setattr(desktop_app, "LoginWindow", FakeLoginWindow)
    monkeypatch.setattr(desktop_app, "FemagDesktopWindow", FakeDesktopWindow)
    monkeypatch.setattr(desktop_app, "femag_icon", lambda: None)
    monkeypatch.setattr(desktop_app, "stylesheet_for", lambda theme: "")
    # `run_desktop_app` arma el tema con `load_theme()`, que lee del
    # `%LOCALAPPDATA%` del operador. Sin esto el test dependeria de la
    # preferencia de tema que tenga en esa maquina.
    monkeypatch.setattr(desktop_app, "load_theme", lambda: desktop_app.Theme.LIGHT)
    monkeypatch.setattr(desktop_app, "_prepare_database", lambda **kwargs: None)
    monkeypatch.setattr(desktop_app, "PermissionService", FakePermissionService)
    monkeypatch.setattr(desktop_app, "_ensure_demo_user", lambda **kwargs: None)
    monkeypatch.setattr(desktop_app, "_seed_demo_masters", lambda: None)
    monkeypatch.setattr(desktop_app, "_record_workstation_version", lambda: None)
    return fake_app


def test_run_desktop_app_releases_main_window_before_returning(monkeypatch):
    """#674: la ventana principal no puede sobrevivir a ``run_desktop_app``.

    Cerrar una ventana en Qt sólo la oculta: el ``QMainWindow`` sigue vivo
    hasta que se libera su wrapper de Python. Si eso recién ocurre durante
    ``Py_FinalizeEx``, la ``QApplication`` y el estado de QtWidgets ya se
    están desmontando y el proceso termina con ``0xC0000005``.
    """
    import app.ui.desktop_app as desktop_app

    events: list = []
    _fake_desktop_environment(monkeypatch, events)

    result = desktop_app.run_desktop_app(demo_mode=True)

    assert result == 0
    assert "window.show" in events
    assert "app.exec_" in events
    assert "window.deleteLater" in events

    destroyed_at = events.index("window.deleteLater")
    assert destroyed_at > events.index("app.exec_")
    # La destrucción tiene que completarse antes de devolver, no quedar en
    #cola para que la resuelva el cierre del intérprete.
    assert ("app.sendPostedEvents", desktop_app.QEvent.DeferredDelete) in events[destroyed_at:]


def test_run_desktop_app_releases_window_also_when_session_is_reopened(monkeypatch):
    """Al cerrar sesión y volver al login la ventana vieja tampoco puede quedar viva."""
    import app.ui.desktop_app as desktop_app

    events: list = []
    _fake_desktop_environment(monkeypatch, events, session_closed=True)

    # Con ``session_closed`` el loop volvería al login indefinidamente: el fake
    # alcanza a hacer el login una vez y luego rejects, así se observa una sola
    # vuelta completa por el loop.
    original_fake_login = desktop_app.LoginWindow

    class OneShotLogin(original_fake_login):
        calls = 0

        def show(self):
            OneShotLogin.calls += 1
            if OneShotLogin.calls > 1:
                return 0  # QDialog.Rejected -> run_desktop_app devuelve 0
            return original_fake_login.show(self)

    monkeypatch.setattr(desktop_app, "LoginWindow", OneShotLogin)

    desktop_app.run_desktop_app(demo_mode=True)

    assert events.count("window.deleteLater") == events.count("window.show") == 1


def test_destroy_desktop_window_deletes_real_widget():
    """El helper destruye de verdad el objeto C++ del widget."""
    import sip
    from PyQt5.QtWidgets import QApplication, QWidget

    import app.ui.desktop_app as desktop_app

    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.show()

    desktop_app._destroy_desktop_window(widget)

    assert sip.isdeleted(widget)
    assert app is not None
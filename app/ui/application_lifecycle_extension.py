from __future__ import annotations

from PyQt5.QtWidgets import QApplication


def install_application_lifecycle_extension() -> None:
    """Avoid QApplication quitting in the gap between login and main window.

    LoginWindow runs its own modal event loop. When it is accepted/rejected it
    can temporarily become the last visible top-level window. With Qt's default
    quitOnLastWindowClosed=True, QApplication may schedule a quit before the
    main FEMAG window is shown, making the app exit normally with code 0 right
    after a successful login.
    """
    from app.ui.login_window import LoginWindow
    from app.ui.desktop_app import FemagDesktopWindow

    if getattr(LoginWindow, "_femag_lifecycle_patch", False):
        return

    original_login_init = LoginWindow.__init__
    original_main_init = FemagDesktopWindow.__init__

    def login_init(self, *args, **kwargs):
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)
        original_login_init(self, *args, **kwargs)

    def main_init(self, *args, **kwargs):
        original_main_init(self, *args, **kwargs)
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)

    LoginWindow.__init__ = login_init
    FemagDesktopWindow.__init__ = main_init
    LoginWindow._femag_lifecycle_patch = True
    FemagDesktopWindow._femag_lifecycle_patch = True

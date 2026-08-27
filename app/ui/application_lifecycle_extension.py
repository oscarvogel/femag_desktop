from __future__ import annotations

import logging

from PyQt5.QtWidgets import QApplication, QMainWindow


logger = logging.getLogger("femag.lifecycle")


def install_application_lifecycle_extension() -> None:
    """Keep QApplication alive across login/main-window transitions.

    The login runs in its own modal event loop before the application's main
    event loop starts. Qt may queue an automatic quit when the login becomes
    the last visible window. Re-enabling quitOnLastWindowClosed before
    QApplication.exec_() lets that queued quit fire immediately, producing the
    observed clean exit with code 0.

    FEMAG therefore keeps Qt's implicit last-window shutdown disabled for the
    whole session and quits the event loop explicitly when the main window is
    actually closed. This also preserves the logout loop used by desktop_app.
    """
    from app.ui.login_window import LoginWindow
    from app.ui.desktop_app import FemagDesktopWindow

    if getattr(LoginWindow, "_femag_lifecycle_patch", False):
        return

    original_login_init = LoginWindow.__init__
    original_main_init = FemagDesktopWindow.__init__
    original_close_event = FemagDesktopWindow.closeEvent

    def _keep_application_alive() -> None:
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)

    def login_init(self, *args, **kwargs):
        _keep_application_alive()
        logger.info("Mostrando login con quitOnLastWindowClosed=False")
        original_login_init(self, *args, **kwargs)

    def main_init(self, *args, **kwargs):
        _keep_application_alive()
        original_main_init(self, *args, **kwargs)
        logger.info("Ventana principal creada; QApplication permanece activa")

    def close_event(self, event):
        original_close_event(self, event)
        if event.isAccepted():
            logger.info("Ventana principal cerrada; finalizando event loop")
            app = QApplication.instance()
            if app is not None:
                app.quit()

    LoginWindow.__init__ = login_init
    FemagDesktopWindow.__init__ = main_init
    FemagDesktopWindow.closeEvent = close_event
    LoginWindow._femag_lifecycle_patch = True
    FemagDesktopWindow._femag_lifecycle_patch = True

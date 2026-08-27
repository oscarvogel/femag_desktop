from __future__ import annotations

import logging

from PyQt5.QtWidgets import QApplication, QDialog


logger = logging.getLogger("femag.lifecycle")


def install_application_lifecycle_extension() -> None:
    """Keep QApplication alive and trust a successfully authenticated login.

    Production logs showed the login dialog being displayed and FEMAG then
    returning code 0 without ever constructing the main window. The desktop
    loop historically depends on the QDialog return code, but authentication
    already stores the authoritative result in ``authenticated_user``.

    If authentication succeeded, force an Accepted result even if Qt unwinds
    the modal dialog with another code. Closing/cancelling the login without an
    authenticated user still returns the original dialog result and exits.
    """
    from app.ui.login_window import LoginWindow
    from app.ui.desktop_app import FemagDesktopWindow

    if getattr(LoginWindow, "_femag_lifecycle_patch", False):
        return

    original_login_init = LoginWindow.__init__
    original_login_show = LoginWindow.show
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

    def login_show(self):
        result = original_login_show(self)
        if self.authenticated_user is not None:
            logger.info(
                "Login autenticado; resultado Qt=%s. Continuando con ventana principal",
                result,
            )
            return QDialog.Accepted
        logger.info("Login finalizado sin usuario autenticado; resultado Qt=%s", result)
        return result

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
    LoginWindow.show = login_show
    FemagDesktopWindow.__init__ = main_init
    FemagDesktopWindow.closeEvent = close_event
    LoginWindow._femag_lifecycle_patch = True
    FemagDesktopWindow._femag_lifecycle_patch = True

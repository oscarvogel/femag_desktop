import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_client_edit_without_success_toast(db, monkeypatch):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.form_feedback import FormFeedback

    monkeypatch.setattr(FormFeedback, "show_success", lambda self, message, **kwargs: None)

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="diag_feedback_client", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    table = window.findChild(QTableWidget, "clientTable")

    def fill_new_client():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente Feedback")
        dialog.findChild(QLineEdit, "clientCuitInput").setText("30700000993")
        dialog.findChild(QLineEdit, "clientIvaInput").setText("RI")
        dialog.findChild(QPushButton, "saveClientButton").click()

    QTimer.singleShot(0, fill_new_client)
    window.findChild(QPushButton, "newClientButton").click()
    app.processEvents()

    client = Client.get(Client.cuit == "30700000993")
    assert table.rowCount() == 1

    def fill_edit_client():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente Feedback Editado")
        dialog.findChild(QPushButton, "saveClientButton").click()

    QTimer.singleShot(0, fill_edit_client)
    window.findChild(QPushButton, "editClientButton").click()
    app.processEvents()

    client = Client.get_by_id(client.id)
    assert client.name == "Cliente Feedback Editado"
    assert table.item(0, 0).text() == "Cliente Feedback Editado"
    window.close()

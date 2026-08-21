import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_diagnose_client_create_edit_modal(db):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="diag_clients_abm", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    table = window.findChild(QTableWidget, "clientTable")
    diagnostics = []

    def fill_new_client():
        try:
            dialog = app.activeModalWidget()
            diagnostics.append(("new_modal", type(dialog).__name__ if dialog else None, dialog.objectName() if dialog else None))
            name = dialog.findChild(QLineEdit, "clientNameInput") if dialog else None
            cuit = dialog.findChild(QLineEdit, "clientCuitInput") if dialog else None
            iva = dialog.findChild(QLineEdit, "clientIvaInput") if dialog else None
            save = dialog.findChild(QPushButton, "saveClientButton") if dialog else None
            diagnostics.append(("new_fields", bool(name), bool(cuit), bool(iva), bool(save)))
            assert isinstance(dialog, QDialog)
            assert name and cuit and iva and save
            name.setText("Cliente Diagnostico")
            cuit.setText("30700000992")
            iva.setText("RI")
            save.click()
        except Exception as exc:
            diagnostics.append(("new_error", type(exc).__name__, str(exc)))
            modal = app.activeModalWidget()
            if isinstance(modal, QDialog):
                modal.reject()

    QTimer.singleShot(0, fill_new_client)
    window.findChild(QPushButton, "newClientButton").click()
    app.processEvents()

    client = Client.get(Client.cuit == "30700000992")
    diagnostics.append(("after_new", table.currentRow(), table.rowCount(), client.lista_precios))

    def fill_edit_client():
        try:
            dialog = app.activeModalWidget()
            diagnostics.append(("edit_modal", type(dialog).__name__ if dialog else None, dialog.objectName() if dialog else None))
            name = dialog.findChild(QLineEdit, "clientNameInput") if dialog else None
            save = dialog.findChild(QPushButton, "saveClientButton") if dialog else None
            diagnostics.append(("edit_fields", bool(name), bool(save)))
            assert isinstance(dialog, QDialog)
            assert name and save
            name.setText("Cliente Diagnostico Editado")
            save.click()
        except Exception as exc:
            diagnostics.append(("edit_error", type(exc).__name__, str(exc)))
            modal = app.activeModalWidget()
            if isinstance(modal, QDialog):
                modal.reject()

    QTimer.singleShot(0, fill_edit_client)
    window.findChild(QPushButton, "editClientButton").click()
    app.processEvents()

    print("CLIENT_ABM_DIAGNOSTICS", diagnostics)
    assert not [item for item in diagnostics if item[0].endswith("_error")], diagnostics
    client = Client.get_by_id(client.id)
    assert client.name == "Cliente Diagnostico Editado"
    window.close()

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_client_email_service_manages_multiple_contacts_and_primary(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.client_email_service import ClientEmailService

    client = Client.create(name="Cliente emails", cuit="30700000280", iva_condition="RI")
    service = ClientEmailService("admin_280")

    first = service.create(
        client=client,
        email=" ADMIN@Example.com ",
        label="Administracion",
    )
    second = service.create(
        client=client,
        email="pagos@example.com",
        label="Pagos",
        is_primary=True,
    )

    first = type(first).get_by_id(first.id)
    client = Client.get_by_id(client.id)
    assert first.email == "admin@example.com"
    assert not first.is_primary
    assert second.is_primary
    assert client.email == "pagos@example.com"
    assert [row.email for row in service.active_for_client(client)] == [
        "pagos@example.com",
        "admin@example.com",
    ]
    assert AuditLog.select().where(AuditLog.action == "crear_email").count() == 2


def test_client_email_rejects_duplicate_and_promotes_active_fallback(db):
    from app.models.masters import Client, ClientEmail
    from app.services.client_email_service import ClientEmailError, ClientEmailService

    client = Client.create(name="Cliente duplicado", cuit="30700001280", iva_condition="RI")
    service = ClientEmailService("admin_280")
    first = service.create(client=client, email="uno@example.com")
    second = service.create(client=client, email="dos@example.com")

    with pytest.raises(ClientEmailError, match="ya tiene registrado"):
        service.create(client=client, email="UNO@example.com")

    service.toggle_active(first)
    second = ClientEmail.get_by_id(second.id)
    assert second.is_primary
    assert Client.get_by_id(client.id).email == "dos@example.com"
    service.toggle_active(first)
    service.set_primary(first)
    assert ClientEmail.get_by_id(first.id).is_primary
    assert not ClientEmail.get_by_id(second.id).is_primary


def test_runtime_schema_backfills_legacy_client_email(db):
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Client, ClientEmail

    client = Client.create(
        name="Cliente legacy email",
        cuit="30700002280",
        iva_condition="RI",
        email="LEGACY@Example.com",
    )

    ensure_runtime_schema(db)

    row = ClientEmail.get(ClientEmail.client == client)
    assert row.email == "legacy@example.com"
    assert row.label == "Legacy"
    assert row.is_primary
    assert row.active
    assert Client.get_by_id(client.id).email == "LEGACY@Example.com"


def test_client_email_dialog_and_manager_expose_contact_workflow(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client, ClientEmail
    from app.ui.master_abm import ClientEmailEntryDialog, ClientEmailsDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente UI email", cuit="30700003280", iva_condition="RI")
    entry = ClientEmailEntryDialog(current_user="admin_ui_280", client_id=client.id)
    entry.findChild(QLineEdit, "clientContactEmailInput").setText("compras@example.com")
    entry.findChild(QLineEdit, "clientContactEmailLabelInput").setText("Compras")
    entry.findChild(QPushButton, "saveClientContactEmailButton").click()

    saved = ClientEmail.get(ClientEmail.client == client)
    assert saved.is_primary
    manager = ClientEmailsDialog(current_user="admin_ui_280", client_id=client.id)
    app.processEvents()
    table = manager.findChild(QTableWidget, "clientEmailsTable")
    assert table.rowCount() == 1
    assert [table.item(0, column).text() for column in range(4)] == [
        "compras@example.com",
        "Compras",
        "Si",
        "Activo",
    ]
    assert manager.findChild(QPushButton, "addClientEmailButton") is not None
    assert manager.findChild(QPushButton, "editClientEmailButton") is not None
    assert manager.findChild(QPushButton, "toggleClientEmailButton") is not None
    assert manager.findChild(QPushButton, "setPrimaryClientEmailButton") is not None

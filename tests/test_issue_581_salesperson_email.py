"""Campo Email del vendedor (FEMAG Desktop #581).

Cubre la carga en el maestro, la normalizacion y el mensaje claro cuando falta
o es invalido, que es lo que despues usa el envio del resumen de cartera.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_create_salesperson_normalizes_email(db):
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")

    salesperson = service.create_salesperson(
        "Luis", phone="0376 15 4123456", email="  Luis@Example.COM "
    )

    assert salesperson.email == "luis@example.com"


def test_create_salesperson_without_email_keeps_it_null(db):
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")

    assert service.create_salesperson("Luis").email is None
    assert service.create_salesperson("Maria", email="   ").email is None


def test_create_salesperson_rejects_invalid_email(db):
    import pytest

    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")

    with pytest.raises(ValueError) as error:
        service.create_salesperson("Luis", email="luis@example")

    assert "email valido" in str(error.value)


def test_update_salesperson_changes_email_and_audits_it(db):
    from app.models.audit import AuditLog
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    service = MasterService(current_user="admin")
    salesperson = service.create_salesperson("Luis", email="viejo@example.com")

    service.update_salesperson(
        salesperson, "Luis", phone="0376 15 4123456", email="nuevo@example.com"
    )

    assert Salesperson.get_by_id(salesperson.id).email == "nuevo@example.com"

    event = AuditLog.get(
        (AuditLog.record_ref == f"Salesperson:{salesperson.id}")
        & (AuditLog.action == "modificar")
    )
    assert event.old_value["email"] == "viejo@example.com"
    assert event.new_value["email"] == "nuevo@example.com"


def test_salesperson_dialog_saves_email(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

    from app.models.masters import Salesperson
    from app.ui.master_abm import SalespersonEntryDialog

    app = QApplication.instance() or QApplication([])
    assert app is not None

    dialog = SalespersonEntryDialog(current_user="admin")
    dialog.findChild(QLineEdit, "salespersonNameInput").setText("Luis")
    dialog.findChild(QLineEdit, "salespersonPhoneInput").setText("0376 15 4123456")
    dialog.findChild(QLineEdit, "salespersonEmailInput").setText("Luis@Example.com")
    dialog.findChild(QPushButton, "saveSalespersonButton").click()

    assert Salesperson.get(Salesperson.name == "Luis").email == "luis@example.com"


def test_salesperson_rows_expose_email_column(db):
    from app.services.master_service import MasterService
    from app.ui.master_abm import _salesperson_rows

    MasterService(current_user="admin").create_salesperson(
        "Luis", email="luis@example.com"
    )

    rows = _salesperson_rows()

    assert rows[0][1] == "Luis"
    assert rows[0][3] == "luis@example.com"

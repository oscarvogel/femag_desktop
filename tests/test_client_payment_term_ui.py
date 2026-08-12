import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_client_editor_creates_payment_term_days(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton, QSpinBox

    from app.models.masters import Client
    from app.ui.master_abm import ClientEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = ClientEntryDialog(current_user="issue256")
    dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente plazo UI")
    dialog.findChild(QLineEdit, "clientCuitInput").setText("30700000256")
    dialog.findChild(QLineEdit, "clientIvaInput").setText("RI")
    term = dialog.findChild(QSpinBox, "clientPaymentTermDaysInput")

    assert term is not None
    assert term.minimum() == 0
    assert term.value() == 0

    term.setValue(15)
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    client = Client.get(Client.cuit == "30700000256")
    assert client.dias_plazo_pago == 15


def test_client_editor_loads_and_updates_payment_term_days(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QSpinBox

    from app.models.masters import Client
    from app.ui.master_abm import ClientEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente edición plazo",
        cuit="30700010256",
        iva_condition="RI",
        dias_plazo_pago=7,
    )

    dialog = ClientEntryDialog(current_user="issue256", record_id=client.id)
    term = dialog.findChild(QSpinBox, "clientPaymentTermDaysInput")
    assert term is not None
    assert term.value() == 7

    term.setValue(30)
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    assert Client.get_by_id(client.id).dias_plazo_pago == 30

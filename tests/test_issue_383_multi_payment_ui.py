import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_payment_dialog_supports_multiple_methods_and_total(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.models.payments import ClientPaymentDetail
    from app.ui.customer_payment_dialog import ClientPaymentDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Pago Compuesto",
        cuit="30700000383",
        iva_condition="RI",
    )

    dialog = ClientPaymentDialog(current_user="admin", preset_client=client)
    dialog.amount_input.setValue(500)
    dialog.add_detail_row()

    method = dialog.details_table.cellWidget(1, 0)
    reference = dialog.details_table.cellWidget(1, 1)
    amount = dialog.details_table.cellWidget(1, 2)
    method.setCurrentIndex(method.findData("retenciones_percepciones"))
    reference.setText("IIBB-2026-09")
    amount.setValue(125)

    assert dialog.details_table.rowCount() == 2
    assert "625" in dialog.total_label.text()

    dialog._on_accept()
    payment = dialog.registered_payment()
    assert payment is not None
    assert payment.amount == 625
    assert payment.method == "multiple"
    details = list(
        ClientPaymentDetail.select()
        .where(ClientPaymentDetail.payment == payment)
        .order_by(ClientPaymentDetail.sequence)
    )
    assert len(details) == 2
    assert details[1].payment_method.name == "Retenciones / Percepciones"
    assert details[1].reference == "IIBB-2026-09"

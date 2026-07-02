from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.models.masters import Client
from app.models.payments import ClientPayment
from app.services.client_payment_service import (
    ClientPaymentError,
    ClientPaymentService,
)


METHOD_LABELS = {
    ClientPayment.METHOD_CASH: "Efectivo",
    ClientPayment.METHOD_TRANSFER: "Transferencia",
    ClientPayment.METHOD_CHECK: "Cheque",
}


class ClientPaymentDialog(QDialog):
    def __init__(
        self,
        *,
        current_user: str,
        service: ClientPaymentService | None = None,
        preset_client: Client | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Registrar pago de cliente")
        self.setModal(True)
        self.resize(420, 280)
        self.current_user = current_user
        self.service = service or ClientPaymentService(current_user=current_user)
        self._registered_payment: ClientPayment | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Registrar un nuevo pago contra la cuenta corriente del cliente."))

        form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientPaymentClientCombo")
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        if preset_client is not None:
            idx = self.client_combo.findData(preset_client.id)
            if idx >= 0:
                self.client_combo.setCurrentIndex(idx)
        form.addRow("Cliente", self.client_combo)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setObjectName("clientPaymentAmountInput")
        self.amount_input.setRange(0.0, 99999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setSingleStep(100.0)
        self.amount_input.setPrefix("$ ")
        form.addRow("Monto", self.amount_input)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setObjectName("clientPaymentDateInput")
        self.date_input.setCalendarPopup(True)
        form.addRow("Fecha", self.date_input)

        self.method_combo = QComboBox()
        self.method_combo.setObjectName("clientPaymentMethodCombo")
        for method in ClientPayment.METHODS:
            self.method_combo.addItem(METHOD_LABELS.get(method, method), method)
        form.addRow("Medio", self.method_combo)

        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("clientPaymentReferenceInput")
        self.reference_input.setPlaceholderText("Nro. de transferencia, cheque, etc.")
        form.addRow("Referencia", self.reference_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("clientPaymentSaveButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("clientPaymentCancelButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def registered_payment(self) -> ClientPayment | None:
        return self._registered_payment

    def _on_accept(self) -> None:
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, "Pago", "Debe seleccionar un cliente.")
            return
        amount = self.amount_input.value()
        if amount <= 0:
            QMessageBox.warning(self, "Pago", "El monto debe ser mayor a cero.")
            return
        try:
            payment = self.service.register_payment(
                client=Client.get_by_id(client_id),
                amount=amount,
                payment_date=self.date_input.date().toPyDate(),
                method=self.method_combo.currentData(),
                reference=self.reference_input.text().strip() or None,
            )
        except ClientPaymentError as exc:
            QMessageBox.warning(self, "Pago", str(exc))
            return
        self._registered_payment = payment
        self.accept()

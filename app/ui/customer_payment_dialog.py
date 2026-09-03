from __future__ import annotations

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.masters import Client
from app.models.payments import ClientPayment
from app.services.client_payment_service import (
    ClientPaymentError,
    ClientPaymentService,
)
from app.ui.combo_autocomplete import enable_combo_autocomplete


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
        self.resize(760, 470)
        self.current_user = current_user
        self.service = service or ClientPaymentService(current_user=current_user)
        self._registered_payment: ClientPayment | None = None
        self._method_options = self.service.active_payment_methods()

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Registre uno o varios medios/comprobantes. "
                "El total del recibo se calcula automáticamente."
            )
        )

        form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientPaymentClientCombo")
        enable_combo_autocomplete(self.client_combo, placeholder="Buscar cliente...")
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        if preset_client is not None:
            idx = self.client_combo.findData(preset_client.id)
            if idx >= 0:
                self.client_combo.setCurrentIndex(idx)
        form.addRow("Cliente", self.client_combo)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setObjectName("clientPaymentDateInput")
        self.date_input.setCalendarPopup(True)
        form.addRow("Fecha", self.date_input)
        layout.addLayout(form)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Medios / comprobantes"))
        toolbar.addStretch(1)
        add_button = QPushButton("Agregar medio")
        add_button.setObjectName("clientPaymentAddDetailButton")
        add_button.clicked.connect(self.add_detail_row)
        remove_button = QPushButton("Eliminar línea")
        remove_button.setObjectName("clientPaymentRemoveDetailButton")
        remove_button.clicked.connect(self.remove_selected_row)
        toolbar.addWidget(add_button)
        toolbar.addWidget(remove_button)
        layout.addLayout(toolbar)

        self.details_table = QTableWidget(0, 3)
        self.details_table.setObjectName("clientPaymentDetailsTable")
        self.details_table.setHorizontalHeaderLabels(["Medio", "Referencia / comprobante", "Importe"])
        header = self.details_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.details_table.verticalHeader().setVisible(False)
        self.details_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.details_table, 1)

        total_row = QHBoxLayout()
        total_row.addStretch(1)
        total_row.addWidget(QLabel("Total del recibo:"))
        self.total_label = QLabel("$ 0,00")
        self.total_label.setObjectName("clientPaymentTotalLabel")
        self.total_label.setStyleSheet("font-weight: 700; font-size: 16px;")
        total_row.addWidget(self.total_label)
        layout.addLayout(total_row)

        self.add_detail_row()
        # Alias de compatibilidad para tests/código que trabajaban con el formulario simple.
        self.method_combo = self.details_table.cellWidget(0, 0)
        self.reference_input = self.details_table.cellWidget(0, 1)
        self.amount_input = self.details_table.cellWidget(0, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("clientPaymentSaveButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("clientPaymentCancelButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _new_method_combo(self) -> QComboBox:
        combo = QComboBox()
        enable_combo_autocomplete(combo, placeholder="Buscar medio...")
        for method in self._method_options:
            combo.addItem(method.name, method.code)
        return combo

    def _new_amount_input(self) -> QDoubleSpinBox:
        amount = QDoubleSpinBox()
        amount.setRange(0.0, 9999999999.99)
        amount.setDecimals(2)
        amount.setSingleStep(100.0)
        amount.setPrefix("$ ")
        amount.valueChanged.connect(self._refresh_total)
        return amount

    def add_detail_row(self) -> None:
        row = self.details_table.rowCount()
        self.details_table.insertRow(row)
        method = self._new_method_combo()
        reference = QLineEdit()
        reference.setPlaceholderText("Nro. transferencia, cheque, retención, etc.")
        amount = self._new_amount_input()
        self.details_table.setCellWidget(row, 0, method)
        self.details_table.setCellWidget(row, 1, reference)
        self.details_table.setCellWidget(row, 2, amount)
        self.details_table.setItem(row, 0, QTableWidgetItem())
        self._refresh_total()

    def remove_selected_row(self) -> None:
        if self.details_table.rowCount() <= 1:
            QMessageBox.information(self, "Pago", "Debe quedar al menos una línea de pago.")
            return
        row = self.details_table.currentRow()
        if row < 0:
            row = self.details_table.rowCount() - 1
        self.details_table.removeRow(row)
        self._refresh_total()

    def _details(self) -> list[dict]:
        rows = []
        for row in range(self.details_table.rowCount()):
            method = self.details_table.cellWidget(row, 0)
            reference = self.details_table.cellWidget(row, 1)
            amount = self.details_table.cellWidget(row, 2)
            rows.append(
                {
                    "method": method.currentData(),
                    "reference": reference.text().strip() or None,
                    "amount": amount.value(),
                }
            )
        return rows

    def _refresh_total(self) -> None:
        total = 0.0
        for row in range(self.details_table.rowCount()):
            widget = self.details_table.cellWidget(row, 2)
            if widget is not None:
                total += widget.value()
        formatted = f"$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.total_label.setText(formatted)

    def registered_payment(self) -> ClientPayment | None:
        return self._registered_payment

    def _on_accept(self) -> None:
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, "Pago", "Debe seleccionar un cliente.")
            return
        details = self._details()
        if not details or any(float(row.get("amount") or 0) <= 0 for row in details):
            QMessageBox.warning(
                self,
                "Pago",
                "Todas las líneas deben tener un importe mayor a cero.",
            )
            return
        try:
            payment = self.service.register_compound_payment(
                client=Client.get_by_id(client_id),
                payment_date=self.date_input.date().toPyDate(),
                details=details,
            )
        except ClientPaymentError as exc:
            QMessageBox.warning(self, "Pago", str(exc))
            return
        self._registered_payment = payment
        self.accept()

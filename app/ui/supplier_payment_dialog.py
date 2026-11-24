"""Dialogo para registrar un pago a un productor (#941).

El pago se arma desde las imputaciones: el operador dice cuanto le paga de cada
ticket pendiente y el importe del pago es la suma. Asi no hay forma de cargar
un pago que no coincida con lo imputado, y cada imputacion tiene como tope el
pendiente del ticket: ninguna puede dejarlo en negativo.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.suppliers import SupplierPayment
from app.services.supplier_position_service import SupplierDocumentRow

METHOD_LABELS = {
    SupplierPayment.METHOD_TRANSFER: "Transferencia",
    SupplierPayment.METHOD_CASH: "Efectivo",
    SupplierPayment.METHOD_CHECK: "Cheque",
    SupplierPayment.METHOD_OTHER: "Otros",
}


def format_money(value) -> str:
    text = f"{Decimal(str(value)):,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


class SupplierPaymentDialog(QDialog):
    HEADERS = ("Ticket", "Fecha", "Pendiente", "Imputar")

    def __init__(self, supplier_name: str, tickets: list[SupplierDocumentRow], parent=None):
        super().__init__(parent)
        self.setObjectName("supplierPaymentDialog")
        self.setWindowTitle(f"Registrar pago - {supplier_name}")
        self.resize(760, 560)
        self.tickets = [ticket for ticket in tickets if ticket.pending > 0]
        # Una clave por dialogo: si el guardado se dispara dos veces, el libro
        # devuelve el mismo pago en vez de registrar otro.
        self.idempotency_key = uuid.uuid4().hex
        self._spins: list[QDoubleSpinBox] = []
        self._build_ui(supplier_name)
        self._update_total()

    def _build_ui(self, supplier_name: str) -> None:
        root = QVBoxLayout(self)
        title = QLabel(f"Pago a {supplier_name}")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        hint = QLabel(
            "Indique cuánto se paga de cada ticket. El importe del pago es la suma de lo imputado."
        )
        hint.setStyleSheet("color:#64748b;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.date_edit = QDateEdit(calendarPopup=True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.method_combo = QComboBox()
        for code, label in METHOD_LABELS.items():
            self.method_combo.addItem(label, code)
        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("N° de transferencia, cheque, etc.")
        self.reference_edit.setMaxLength(120)
        self.observations_edit = QPlainTextEdit()
        self.observations_edit.setFixedHeight(56)
        form.addRow("Fecha", self.date_edit)
        form.addRow("Medio", self.method_combo)
        form.addRow("Referencia", self.reference_edit)
        form.addRow("Observación", self.observations_edit)
        root.addLayout(form)

        self.table = QTableWidget(len(self.tickets), len(self.HEADERS))
        self.table.setObjectName("supplierPaymentAllocations")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, ticket in enumerate(self.tickets):
            self.table.setItem(row, 0, QTableWidgetItem(ticket.code))
            fecha = ticket.issued_at.strftime("%d/%m/%Y") if ticket.issued_at else ""
            self.table.setItem(row, 1, QTableWidgetItem(fecha))
            pending = QTableWidgetItem(format_money(ticket.pending))
            pending.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, pending)
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(0, float(ticket.pending))
            spin.setGroupSeparatorShown(True)
            spin.setAlignment(Qt.AlignRight)
            spin.valueChanged.connect(self._update_total)
            self.table.setCellWidget(row, 3, spin)
            self._spins.append(spin)
        for column, width in enumerate((140, 100, 150)):
            self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        tools = QHBoxLayout()
        fill = QPushButton("Saldar seleccionados")
        fill.setToolTip("Completa la imputación de los tickets seleccionados con todo su pendiente.")
        fill.clicked.connect(self.fill_selected)
        clear = QPushButton("Limpiar imputaciones")
        clear.clicked.connect(self.clear_allocations)
        tools.addWidget(fill)
        tools.addWidget(clear)
        tools.addStretch(1)
        self.total_label = QLabel()
        self.total_label.setObjectName("supplierPaymentTotal")
        self.total_label.setStyleSheet("font-size:16px;font-weight:700;")
        tools.addWidget(self.total_label)
        root.addLayout(tools)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Registrar pago")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def set_allocation(self, row: int, value) -> None:
        self._spins[row].setValue(float(value))

    def fill_selected(self) -> None:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        for row in rows:
            self._spins[row].setValue(float(self.tickets[row].pending))

    def clear_allocations(self) -> None:
        for spin in self._spins:
            spin.setValue(0)

    def allocations(self) -> list[tuple[SupplierDocumentRow, Decimal]]:
        result = []
        for ticket, spin in zip(self.tickets, self._spins):
            amount = Decimal(str(round(spin.value(), 2))).quantize(Decimal("0.01"))
            if amount > 0:
                result.append((ticket, amount))
        return result

    def total(self) -> Decimal:
        return sum((amount for _, amount in self.allocations()), Decimal("0.00"))

    def _update_total(self, *_args) -> None:
        total = self.total()
        self.total_label.setText(f"Total del pago: $ {format_money(total)}")
        self.buttons.button(QDialogButtonBox.Save).setEnabled(total > 0)

    def payment_date(self) -> date:
        return self.date_edit.date().toPyDate()

    def method(self) -> str:
        return self.method_combo.currentData()

    def reference(self) -> str:
        return self.reference_edit.text().strip()

    def observations(self) -> str:
        return self.observations_edit.toPlainText().strip()

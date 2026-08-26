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
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder, LoadOrderClosure
from app.models.masters import Client
from app.models.payments import ClientPayment
from app.services.load_order_closure_service import LoadOrderClosureService
from app.ui.combo_autocomplete import enable_combo_autocomplete


METHOD_LABELS = {
    ClientPayment.METHOD_CASH: "Efectivo",
    ClientPayment.METHOD_TRANSFER: "Transferencia",
    ClientPayment.METHOD_CHECK: "Cheque",
    ClientPayment.METHOD_OTHER: "Otros",
}


class LoadOrderClosureDialog(QDialog):
    """Capture delivery payments and returned quantities before closing an order."""

    def __init__(
        self,
        *,
        order: LoadOrder,
        current_user: str,
        service: LoadOrderClosureService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.order = LoadOrder.get_by_id(order.id)
        self.service = service or LoadOrderClosureService(current_user=current_user)
        self._closure: LoadOrderClosure | None = None
        self._payments: list[dict] = []
        self._return_inputs: list[tuple[object, QDoubleSpinBox, QLineEdit, QTableWidgetItem]] = []

        self.setWindowTitle(f"Cerrar entrega OC-{self.order.order_number:06d}")
        self.setModal(True)
        self.resize(1050, 760)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Renglones emitidos y devoluciones"))
        self.lines_table = QTableWidget(0, 8)
        self.lines_table.setObjectName("loadOrderClosureLinesTable")
        self.lines_table.setHorizontalHeaderLabels(
            [
                "Cliente",
                "Producto",
                "Cantidad",
                "Precio unitario",
                "Total",
                "Cant. devuelta",
                "Motivo devolución",
                "A acreditar",
            ]
        )
        self.lines_table.setMinimumHeight(170)
        self.lines_table.horizontalHeader().setStretchLastSection(True)
        self._load_lines()
        layout.addWidget(self.lines_table)

        payment_form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("loadOrderClosureClientCombo")
        enable_combo_autocomplete(self.client_combo, placeholder="Buscar cliente...")
        for client in self._order_clients():
            self.client_combo.addItem(client.name, client.id)
        payment_form.addRow("Cliente", self.client_combo)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setObjectName("loadOrderClosureAmountInput")
        self.amount_input.setRange(0.0, 99999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setPrefix("$ ")
        payment_form.addRow("Monto", self.amount_input)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setObjectName("loadOrderClosurePaymentDateInput")
        self.date_input.setCalendarPopup(True)
        payment_form.addRow("Fecha", self.date_input)

        self.method_combo = QComboBox()
        self.method_combo.setObjectName("loadOrderClosureMethodCombo")
        enable_combo_autocomplete(self.method_combo, placeholder="Buscar medio...")
        for method in ClientPayment.METHODS:
            self.method_combo.addItem(METHOD_LABELS.get(method, method), method)
        payment_form.addRow("Medio", self.method_combo)

        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("loadOrderClosureReferenceInput")
        self.reference_input.setPlaceholderText("Transferencia, cheque u otra referencia")
        payment_form.addRow("Referencia", self.reference_input)
        layout.addLayout(payment_form)

        payment_actions = QHBoxLayout()
        self.add_payment_button = QPushButton("Agregar pago")
        self.add_payment_button.setObjectName("loadOrderClosureAddPaymentButton")
        self.remove_payment_button = QPushButton("Quitar pago")
        self.remove_payment_button.setObjectName("loadOrderClosureRemovePaymentButton")
        payment_actions.addWidget(self.add_payment_button)
        payment_actions.addWidget(self.remove_payment_button)
        payment_actions.addStretch(1)
        layout.addLayout(payment_actions)

        self.payments_table = QTableWidget(0, 5)
        self.payments_table.setObjectName("loadOrderClosurePaymentsTable")
        self.payments_table.setHorizontalHeaderLabels(
            ["Cliente", "Fecha", "Medio", "Referencia", "Monto"]
        )
        self.payments_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.payments_table.setMinimumHeight(100)
        self.payments_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.payments_table)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("loadOrderClosurePaymentSummary")
        layout.addWidget(self.summary_label)

        self.return_summary_label = QLabel()
        self.return_summary_label.setObjectName("loadOrderClosureReturnSummary")
        layout.addWidget(self.return_summary_label)

        self.no_payment_reason_input = QLineEdit()
        self.no_payment_reason_input.setObjectName("loadOrderClosureNoPaymentReasonInput")
        self.no_payment_reason_input.setPlaceholderText(
            "Obligatorio si se cierra sin pagos; el saldo queda en cuenta corriente"
        )
        layout.addWidget(QLabel("Motivo de cierre sin pago"))
        layout.addWidget(self.no_payment_reason_input)

        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("loadOrderClosureObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones generales de la entrega")
        layout.addWidget(QLabel("Observaciones"))
        layout.addWidget(self.observations_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Cerrar entrega")
        buttons.button(QDialogButtonBox.Save).setObjectName("loadOrderClosureSaveButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("loadOrderClosureCancelButton")
        layout.addWidget(buttons)

        self.add_payment_button.clicked.connect(self._add_payment)
        self.remove_payment_button.clicked.connect(self._remove_payment)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._refresh_summary()
        self._refresh_return_summary()

    def closure(self) -> LoadOrderClosure | None:
        return self._closure

    def pending_payments(self) -> list[dict]:
        return list(self._payments)

    def pending_returns(self) -> list[dict]:
        returns = []
        for line, quantity_input, reason_input, _credit_item in self._return_inputs:
            quantity = round(quantity_input.value(), 3)
            if quantity <= 0:
                continue
            returns.append(
                {
                    "order_product": line,
                    "quantity": quantity,
                    "reason": reason_input.text().strip(),
                }
            )
        return returns

    def _load_lines(self) -> None:
        lines = list(self.order.products.order_by())
        self.lines_table.setRowCount(len(lines))
        self._return_inputs.clear()
        for row, line in enumerate(lines):
            client = line.destination.client if line.destination_id else self.order.client
            values = (
                client.name if client else "Sin cliente",
                line.product.name,
                f"{float(line.quantity):,.3f}",
                f"$ {float(line.precio_neto_unitario):,.2f}",
                f"$ {float(line.total):,.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.lines_table.setItem(row, column, item)

            quantity_input = QDoubleSpinBox()
            quantity_input.setObjectName(f"loadOrderClosureReturnQuantityInput_{line.id}")
            quantity_input.setDecimals(3)
            quantity_input.setRange(0.0, max(float(line.quantity), 0.0))
            quantity_input.setSingleStep(1.0)
            self.lines_table.setCellWidget(row, 5, quantity_input)

            reason_input = QLineEdit()
            reason_input.setObjectName(f"loadOrderClosureReturnReasonInput_{line.id}")
            reason_input.setPlaceholderText("Motivo")
            self.lines_table.setCellWidget(row, 6, reason_input)

            credit_item = QTableWidgetItem("$ 0.00")
            credit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            credit_item.setFlags(credit_item.flags() & ~Qt.ItemIsEditable)
            self.lines_table.setItem(row, 7, credit_item)
            self._return_inputs.append((line, quantity_input, reason_input, credit_item))
            quantity_input.valueChanged.connect(self._refresh_return_summary)

    def _order_clients(self) -> list[Client]:
        clients = []
        seen = set()
        for destination in self.order.destinations.order_by():
            if destination.client_id not in seen:
                clients.append(destination.client)
                seen.add(destination.client_id)
        if self.order.client_id and self.order.client_id not in seen:
            clients.append(self.order.client)
        return clients

    def _add_payment(self) -> None:
        client_id = self.client_combo.currentData()
        amount = round(self.amount_input.value(), 2)
        if client_id is None or amount <= 0:
            QMessageBox.warning(self, "Cierre de entrega", "Seleccione un cliente y un monto mayor a cero.")
            return
        payment = {
            "client": Client.get_by_id(client_id),
            "amount": amount,
            "payment_date": self.date_input.date().toPyDate(),
            "method": self.method_combo.currentData(),
            "reference": self.reference_input.text().strip() or None,
        }
        self._payments.append(payment)
        self.amount_input.setValue(0)
        self.reference_input.clear()
        self._refresh_payments_table()

    def _remove_payment(self) -> None:
        row = self.payments_table.currentRow()
        if row < 0:
            return
        self._payments.pop(row)
        self._refresh_payments_table()

    def _refresh_payments_table(self) -> None:
        self.payments_table.setRowCount(len(self._payments))
        for row, payment in enumerate(self._payments):
            values = (
                payment["client"].name,
                payment["payment_date"].strftime("%d/%m/%Y"),
                METHOD_LABELS.get(payment["method"], payment["method"]),
                payment["reference"] or "-",
                f"$ {payment['amount']:,.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.payments_table.setItem(row, column, item)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = sum(float(line.total) for line in self.order.products)
        paid = sum(payment["amount"] for payment in self._payments)
        balance = round(total - paid, 2)
        if balance < -0.009:
            self.summary_label.setText(
                f"Total orden: $ {total:,.2f} | Pagos: $ {paid:,.2f} | "
                f"Saldo a favor: $ {abs(balance):,.2f} (excede total, queda en cuenta corriente)"
            )
        else:
            self.summary_label.setText(
                f"Total orden: $ {total:,.2f} | Pagos: $ {paid:,.2f} | "
                f"Saldo estimado: $ {max(balance, 0):,.2f}"
            )

    def _refresh_return_summary(self, *_args) -> None:
        total_credit = 0.0
        returned_lines = 0
        for line, quantity_input, _reason_input, credit_item in self._return_inputs:
            quantity = round(quantity_input.value(), 3)
            unit_total = float(line.total) / float(line.quantity) if line.quantity else 0.0
            credit = round(unit_total * quantity, 2)
            credit_item.setText(f"$ {credit:,.2f}")
            total_credit += credit
            if quantity > 0:
                returned_lines += 1
        self.return_summary_label.setText(
            f"Devoluciones: {returned_lines} renglón(es) | Monto estimado a acreditar: $ {total_credit:,.2f}"
        )

    def _overpaid_clients(self) -> list[str]:
        totals = self.service._order_totals_by_client(self.order)
        paid_by_client: dict[int, float] = {cid: 0.0 for cid in totals}
        name_by_id = {item["client"].id: item["client"].name for item in self._payments}
        for item in self._payments:
            cid = item["client"].id
            paid_by_client[cid] = round(paid_by_client.get(cid, 0.0) + float(item["amount"]), 2)
        return [
            name_by_id.get(cid) or f"cliente {cid}"
            for cid, total in totals.items()
            if paid_by_client.get(cid, 0.0) > total + 0.009
        ]

    def _on_accept(self) -> None:
        returns = self.pending_returns()
        if any(not item["reason"] for item in returns):
            QMessageBox.warning(
                self,
                "Cierre de entrega",
                "Debe indicar el motivo de cada devolución registrada.",
            )
            return
        overpaid = self._overpaid_clients()
        if overpaid:
            QMessageBox.information(
                self,
                "Cierre de entrega",
                f"Los pagos de {', '.join(overpaid)} superan el total de la orden. "
                f"El excedente quedará como saldo a favor en cuenta corriente.",
            )
        try:
            self._closure = self.service.close_order(
                self.order,
                payments=self._payments,
                returns=returns,
                no_payment_reason=self.no_payment_reason_input.text(),
                observations=self.observations_input.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Cierre de entrega", str(exc))
            return
        except Exception:
            QMessageBox.warning(
                self,
                "Cierre de entrega",
                "No se pudo registrar el cierre. Verifique la conexion e intente nuevamente.",
            )
            return
        self.accept()

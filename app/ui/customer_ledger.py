from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Client
from app.services.ledger_query_service import (
    client_balance,
    client_balances,
    movements_for_client,
    running_balance,
)

MOVEMENT_TYPE_LABELS = {
    "load_order_documental": "Orden de carga",
    "load_order_documental_reversal": "Reverso OC",
    "payment": "Pago",
}


class CustomerLedgerPage(QWidget):
    def __init__(self, *, current_user: str, register_payment_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("customerLedgerPage")
        self.current_user = current_user
        self.register_payment_callback = register_payment_callback

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        title = QLabel("Cuenta corriente por cliente")
        title.setObjectName("customerLedgerTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Listado de clientes con movimientos y saldo consolidado. "
            "Seleccione un cliente para ver el detalle."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_clients_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 720])
        layout.addWidget(splitter, 1)

        self.refresh()

    def _build_clients_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("customerLedgerClientsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        header = QLabel("Clientes con movimientos")
        layout.addWidget(header)

        self.clients_list = QListWidget()
        self.clients_list.setObjectName("customerLedgerClientsList")
        self.clients_list.setAlternatingRowColors(True)
        self.clients_list.currentRowChanged.connect(self._on_client_selected)
        layout.addWidget(self.clients_list, 1)
        return panel

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("customerLedgerDetailPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        self.detail_header = QLabel("Seleccione un cliente de la izquierda.")
        self.detail_header.setObjectName("customerLedgerDetailHeader")
        header_row.addWidget(self.detail_header, 1)

        self.register_payment_button = QPushButton("Registrar pago")
        self.register_payment_button.setObjectName("customerLedgerRegisterPaymentButton")
        self.register_payment_button.setEnabled(False)
        self.register_payment_button.clicked.connect(self._on_register_payment)
        header_row.addWidget(self.register_payment_button)
        layout.addLayout(header_row)

        self.detail_balance = QLabel("")
        self.detail_balance.setObjectName("customerLedgerDetailBalance")
        layout.addWidget(self.detail_balance)

        self.movements_table = QTableWidget(0, 6)
        self.movements_table.setObjectName("customerLedgerMovementsTable")
        self.movements_table.setHorizontalHeaderLabels(
            ["Fecha", "Tipo", "Referencia", "Descripción", "Importe", "Saldo"]
        )
        self.movements_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.movements_table.verticalHeader().setVisible(False)
        self.movements_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.movements_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.movements_table.setAlternatingRowColors(True)
        layout.addWidget(self.movements_table, 1)

        self.empty_label = QLabel(
            "Este cliente no tiene movimientos en su cuenta corriente."
        )
        self.empty_label.setObjectName("customerLedgerEmptyLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)
        return panel

    def refresh(self) -> None:
        previous_id = None
        if self.clients_list.currentItem() is not None:
            previous_id = self.clients_list.currentItem().data(Qt.UserRole)
        self.clients_list.blockSignals(True)
        self.clients_list.clear()
        balances = client_balances()
        for entry in balances:
            client = entry["client"]
            label = f"{client.name}    ${entry['balance']:,.2f}    ({entry['movements']} mov.)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, client.id)
            self.clients_list.addItem(item)
        if balances:
            target_row = 0
            if previous_id is not None:
                for index in range(self.clients_list.count()):
                    if self.clients_list.item(index).data(Qt.UserRole) == previous_id:
                        target_row = index
                        break
            self.clients_list.setCurrentRow(target_row)
        self.clients_list.blockSignals(False)
        if self.clients_list.currentRow() >= 0:
            self._on_client_selected(self.clients_list.currentRow())
        else:
            self._clear_detail()

    def _on_client_selected(self, row: int) -> None:
        item = self.clients_list.item(row)
        if item is None:
            self._clear_detail()
            return
        client = Client.get_by_id(item.data(Qt.UserRole))
        movements = movements_for_client(client)
        balances = running_balance(movements)
        self.detail_header.setText(f"Detalle de cuenta corriente — {client.name}")
        total = client_balance(client)
        self.detail_balance.setText(
            f"Saldo actual: ${total:,.2f}  ·  Movimientos: {len(movements)}"
        )
        self.movements_table.setRowCount(len(movements))
        self.movements_table.setVisible(bool(movements))
        self.empty_label.setVisible(not bool(movements))
        for row_index, movement in enumerate(movements):
            type_label = MOVEMENT_TYPE_LABELS.get(movement.movement_type, movement.movement_type)
            reference = ""
            if movement.load_order is not None:
                reference = f"OC-{movement.load_order.order_number:06d}"
            elif movement.payment is not None:
                reference = movement.payment.receipt_number
            values = (
                movement.created_at.strftime("%d/%m/%Y %H:%M"),
                type_label,
                reference,
                movement.description,
                f"${movement.total_amount:,.2f}",
                f"${balances[row_index]:,.2f}",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (4, 5):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.movements_table.setItem(row_index, column, cell)
        self.register_payment_button.setEnabled(self.register_payment_callback is not None)

    def _clear_detail(self) -> None:
        self.detail_header.setText("Seleccione un cliente de la izquierda.")
        self.detail_balance.setText("")
        self.movements_table.setRowCount(0)
        self.empty_label.hide()
        self.register_payment_button.setEnabled(False)

    def _on_register_payment(self) -> None:
        if self.register_payment_callback is None:
            return
        item = self.clients_list.currentItem()
        if item is None:
            return
        client = Client.get_by_id(item.data(Qt.UserRole))
        self.register_payment_callback(client)
        self.refresh()

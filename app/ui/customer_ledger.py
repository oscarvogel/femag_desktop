from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
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


# Color codes for saldo: positive means client owes us (red warning),
# negative means client has credit in our favor (green positive).
SALDO_COLOR_OWES = QColor("#b91c1c")  # red-700
SALDO_COLOR_CREDIT = QColor("#15803d")  # green-700
SALDO_COLOR_ZERO = QColor("#475569")  # slate-600


def _color_for_balance(value: float) -> QColor:
    if value > 0.01:
        return SALDO_COLOR_OWES
    if value < -0.01:
        return SALDO_COLOR_CREDIT
    return SALDO_COLOR_ZERO


def _apply_color_to_label(label: QLabel, color: QColor) -> None:
    label.setStyleSheet(f"color: {color.name()};")


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
        splitter.setSizes([420, 720])
        layout.addWidget(splitter, 1)

        self.refresh()

    def _build_clients_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("customerLedgerClientsPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        header = QLabel("Clientes con movimientos")
        header.setObjectName("customerLedgerClientsHeader")
        layout.addWidget(header)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("customerLedgerSearchInput")
        self.search_input.setPlaceholderText("Buscar cliente...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        self.only_with_balance = QCheckBox("Solo con saldo")
        self.only_with_balance.setObjectName("customerLedgerOnlyWithBalance")
        self.only_with_balance.toggled.connect(self._on_search_changed)
        layout.addWidget(self.only_with_balance)

        self.clients_table = QTableWidget(0, 3)
        self.clients_table.setObjectName("customerLedgerClientsTable")
        self.clients_table.setHorizontalHeaderLabels(["Cliente", "Saldo", "Movs."])
        self.clients_table.verticalHeader().setVisible(False)
        self.clients_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.clients_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.clients_table.setSelectionMode(QTableWidget.SingleSelection)
        self.clients_table.setAlternatingRowColors(True)
        self.clients_table.setShowGrid(False)
        header_view = self.clients_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.clients_table.verticalHeader().setDefaultSectionSize(28)
        self.clients_table.currentCellChanged.connect(self._on_client_selected)
        layout.addWidget(self.clients_table, 1)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("customerLedgerTotalsLabel")
        self.totals_label.setWordWrap(True)
        layout.addWidget(self.totals_label)
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

        # Highlighted balance card
        balance_card = QFrame()
        balance_card.setObjectName("customerLedgerBalanceCard")
        balance_card.setFrameShape(QFrame.StyledPanel)
        balance_layout = QHBoxLayout(balance_card)
        balance_layout.setContentsMargins(16, 12, 16, 12)
        balance_layout.setSpacing(24)

        saldo_block = QVBoxLayout()
        saldo_label = QLabel("Saldo actual")
        saldo_label.setObjectName("customerLedgerBalanceLabel")
        self.detail_balance = QLabel("$ 0,00")
        self.detail_balance.setObjectName("customerLedgerBalanceValue")
        saldo_block.addWidget(saldo_label)
        saldo_block.addWidget(self.detail_balance)
        balance_layout.addLayout(saldo_block)

        movimientos_block = QVBoxLayout()
        movimientos_label = QLabel("Movimientos")
        movimientos_label.setObjectName("customerLedgerMovementsLabel")
        self.detail_movements = QLabel("0")
        self.detail_movements.setObjectName("customerLedgerMovementsValue")
        movimientos_block.addWidget(movimientos_label)
        movimientos_block.addWidget(self.detail_movements)
        balance_layout.addLayout(movimientos_block)

        balance_layout.addStretch(1)
        layout.addWidget(balance_card)

        self.movements_table = QTableWidget(0, 6)
        self.movements_table.setObjectName("customerLedgerMovementsTable")
        self.movements_table.setHorizontalHeaderLabels(
            ["Fecha", "Tipo", "Referencia", "Descripción", "Importe", "Saldo"]
        )
        movements_header = self.movements_table.horizontalHeader()
        movements_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        movements_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        movements_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        movements_header.setSectionResizeMode(3, QHeaderView.Stretch)
        movements_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        movements_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.movements_table.verticalHeader().setVisible(False)
        self.movements_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.movements_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.movements_table.setAlternatingRowColors(True)
        self.movements_table.setShowGrid(False)
        self.movements_table.verticalHeader().setDefaultSectionSize(26)
        layout.addWidget(self.movements_table, 1)

        self.empty_label = QLabel(
            "Este cliente no tiene movimientos en su cuenta corriente."
        )
        self.empty_label.setObjectName("customerLedgerEmptyLabel")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)
        return panel

    def _on_search_changed(self, *_args) -> None:
        self.refresh()

    def _filter_balances(self, balances: list[dict]) -> list[dict]:
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        only_balance = self.only_with_balance.isChecked() if hasattr(self, "only_with_balance") else False
        filtered: list[dict] = []
        for entry in balances:
            if only_balance and abs(entry["balance"]) <= 0.01:
                continue
            if query and query not in entry["client"].name.lower():
                continue
            filtered.append(entry)
        return filtered

    def refresh(self) -> None:
        previous_id = None
        current = self.clients_table.currentRow()
        if current >= 0:
            item = self.clients_table.item(current, 0)
            if item is not None:
                previous_id = item.data(Qt.UserRole)
        self.clients_table.blockSignals(True)
        self.clients_table.clearContents()
        all_balances = client_balances()
        balances = self._filter_balances(all_balances)
        self.clients_table.setRowCount(len(balances))
        total_to_collect = 0.0
        clients_with_balance = 0
        for row_index, entry in enumerate(balances):
            client = entry["client"]
            balance = entry["balance"]
            movements = entry["movements"]
            if abs(balance) > 0.01:
                clients_with_balance += 1
            if balance > 0.01:
                total_to_collect += balance

            name_cell = QTableWidgetItem(client.name)
            name_cell.setData(Qt.UserRole, client.id)
            name_cell.setToolTip(client.name)
            self.clients_table.setItem(row_index, 0, name_cell)

            balance_text = f"${balance:,.2f}"
            balance_cell = QTableWidgetItem(balance_text)
            balance_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            balance_cell.setForeground(QBrush(_color_for_balance(balance)))
            balance_cell.setToolTip(balance_text)
            self.clients_table.setItem(row_index, 1, balance_cell)

            movements_cell = QTableWidgetItem(str(movements))
            movements_cell.setTextAlignment(Qt.AlignCenter)
            movements_cell.setToolTip(f"{movements} movimiento(s)")
            self.clients_table.setItem(row_index, 2, movements_cell)

        # Totals footer (sobre el conjunto filtrado para que coincida con la tabla)
        suffix = ""
        if len(balances) != len(all_balances):
            suffix = f"  ·  (de {len(all_balances)} totales)"
        self.totals_label.setText(
            f"Total a cobrar: <b>${total_to_collect:,.2f}</b>  ·  "
            f"Clientes con saldo: <b>{clients_with_balance}</b>  ·  "
            f"Total clientes: <b>{len(balances)}</b>{suffix}"
        )

        if balances:
            target_row = 0
            if previous_id is not None:
                for index in range(self.clients_table.rowCount()):
                    if self.clients_table.item(index, 0).data(Qt.UserRole) == previous_id:
                        target_row = index
                        break
            self.clients_table.setCurrentCell(target_row, 0)
        self.clients_table.blockSignals(False)
        if self.clients_table.currentRow() >= 0:
            self._on_client_selected(self.clients_table.currentRow(), 0, -1, -1)
        else:
            self._clear_detail()

    def _on_client_selected(self, current_row, _current_col, _previous_row, _previous_col) -> None:
        if current_row < 0:
            self._clear_detail()
            return
        item = self.clients_table.item(current_row, 0)
        if item is None:
            self._clear_detail()
            return
        client = Client.get_by_id(item.data(Qt.UserRole))
        movements = movements_for_client(client)
        balances = running_balance(movements)
        self.detail_header.setText(f"Detalle de cuenta corriente — {client.name}")
        total = client_balance(client)
        self.detail_balance.setText(f"${total:,.2f}")
        _apply_color_to_label(self.detail_balance, _color_for_balance(total))
        self.detail_movements.setText(str(len(movements)))
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
            importe = movement.total_amount
            importe_text = f"${importe:,.2f}"
            saldo_text = f"${balances[row_index]:,.2f}"
            values = (
                movement.created_at.strftime("%d/%m/%Y %H:%M"),
                type_label,
                reference,
                movement.description,
                importe_text,
                saldo_text,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (4, 5):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if column == 4:
                    cell.setForeground(QBrush(_color_for_balance(importe)))
                if column == 5:
                    cell.setForeground(QBrush(_color_for_balance(balances[row_index])))
                # Tooltip con texto completo para todas las celdas
                cell.setToolTip(value)
                self.movements_table.setItem(row_index, column, cell)
        self.register_payment_button.setEnabled(self.register_payment_callback is not None)

    def _clear_detail(self) -> None:
        self.detail_header.setText("Seleccione un cliente de la izquierda.")
        self.detail_balance.setText("$ 0,00")
        _apply_color_to_label(self.detail_balance, SALDO_COLOR_ZERO)
        self.detail_movements.setText("0")
        self.movements_table.setRowCount(0)
        self.empty_label.hide()
        self.register_payment_button.setEnabled(False)

    def _on_register_payment(self) -> None:
        if self.register_payment_callback is None:
            return
        current = self.clients_table.currentRow()
        if current < 0:
            return
        item = self.clients_table.item(current, 0)
        if item is None:
            return
        client = Client.get_by_id(item.data(Qt.UserRole))
        self.register_payment_callback(client)
        self.refresh()
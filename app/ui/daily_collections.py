from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.models.payments import PaymentMethod
from app.reports.daily_collections import DailyCollectionsFilters, DailyCollectionsReportService


class NumericTableItem(QTableWidgetItem):
    def __init__(self, text: str, value: float | int):
        super().__init__(text)
        self.setData(Qt.UserRole, value)

    def __lt__(self, other):
        if isinstance(other, QTableWidgetItem):
            left = self.data(Qt.UserRole)
            right = other.data(Qt.UserRole)
            if left is not None and right is not None:
                return left < right
        return super().__lt__(other)


class DailyCollectionsDialog(QDialog):
    COLLECTION_HEADERS = (
        "Fecha",
        "Recibo",
        "Cliente",
        "Importe",
        "Medio",
        "Referencia",
        "Orden",
        "Transportista",
        "Usuario",
        "Estado",
        "Observaciones",
    )
    MOVEMENT_HEADERS = (
        "Fecha",
        "Cliente",
        "Tipo",
        "Descripción",
        "Débito",
        "Crédito",
        "Saldo",
        "Moneda",
        "Vencimiento",
        "Orden",
        "Usuario",
        "Reverso",
    )

    def __init__(self, parent=None, *, service: DailyCollectionsReportService | None = None):
        super().__init__(parent)
        self.service = service or DailyCollectionsReportService()
        self.setWindowTitle("Informe operativo · Cobranzas y movimientos")
        self.resize(1480, 820)
        self._build_ui()
        self._load_filters()
        self._set_default_period()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Cobranzas y movimientos de cuenta corriente")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        subtitle = QLabel(
            "Consulta auditable de recibos, medios de pago y movimientos contables del período."
        )
        subtitle.setStyleSheet("color:#64748b;")
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.client_combo = QComboBox()
        self.movement_combo = QComboBox()
        self.method_combo = QComboBox()
        self.currency_combo = QComboBox()
        self.currency_combo.addItem("ARS", "ARS")
        self.currency_combo.addItem("Todas", None)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Usuario exacto")
        self.reversals_only = QCheckBox("Solo anulaciones/reversos")

        widgets = (
            ("Desde", self.date_from),
            ("Hasta", self.date_to),
            ("Cliente", self.client_combo),
            ("Tipo movimiento", self.movement_combo),
            ("Medio de pago", self.method_combo),
            ("Moneda", self.currency_combo),
            ("Usuario", self.user_edit),
        )
        for column, (label, widget) in enumerate(widgets):
            filters.addWidget(QLabel(label), 0, column)
            filters.addWidget(widget, 1, column)
        filters.addWidget(self.reversals_only, 2, 0, 1, 3)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar filtros")
        clear.clicked.connect(self.clear_filters)
        ledger = QPushButton("Abrir cuenta corriente del cliente")
        ledger.clicked.connect(self.open_selected_client_ledger)
        open_order = QPushButton("Ver orden relacionada")
        open_order.clicked.connect(self.open_selected_order)
        actions.addWidget(consult)
        actions.addWidget(clear)
        actions.addWidget(ledger)
        actions.addWidget(open_order)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.collected_label = QLabel()
        self.payments_label = QLabel()
        self.clients_label = QLabel()
        self.movements_label = QLabel()
        self.debit_credit_label = QLabel()
        for label in (
            self.collected_label,
            self.payments_label,
            self.clients_label,
            self.movements_label,
            self.debit_credit_label,
        ):
            label.setStyleSheet(
                "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
                "border-radius:8px;padding:8px 12px;"
            )
            summary.addWidget(label)
        summary.addStretch(1)
        root.addLayout(summary)

        self.tabs = QTabWidget()
        self.collections_table = self._table(self.COLLECTION_HEADERS)
        self.movements_table = self._table(self.MOVEMENT_HEADERS)
        collections_tab = QWidget()
        collections_layout = QVBoxLayout(collections_tab)
        self.methods_label = QLabel()
        self.methods_label.setWordWrap(True)
        self.methods_label.setStyleSheet("color:#475569;")
        collections_layout.addWidget(self.methods_label)
        collections_layout.addWidget(self.collections_table, 1)
        movements_tab = QWidget()
        movements_layout = QVBoxLayout(movements_tab)
        movements_layout.addWidget(self.movements_table, 1)
        self.tabs.addTab(collections_tab, "Cobranzas")
        self.tabs.addTab(movements_tab, "Movimientos")
        root.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    @staticmethod
    def _table(headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        return table

    def _load_filters(self) -> None:
        self.client_combo.clear()
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)

        self.movement_combo.clear()
        self.movement_combo.addItem("Todos", None)
        movement_types = (
            ClientAccountMovement.TYPE_OPENING_BALANCE,
            ClientAccountMovement.TYPE_LOAD_ORDER,
            ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL,
            ClientAccountMovement.TYPE_PAYMENT,
            ClientAccountMovement.TYPE_PAYMENT_REVERSAL,
            ClientAccountMovement.TYPE_MANUAL_DEBIT,
            ClientAccountMovement.TYPE_MANUAL_DEBIT_REVERSAL,
            ClientAccountMovement.TYPE_MANUAL_CREDIT,
            ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL,
            ClientAccountMovement.TYPE_RETURN_CREDIT,
            ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL,
        )
        for movement_type in movement_types:
            self.movement_combo.addItem(movement_type.replace("_", " ").title(), movement_type)

        self.method_combo.clear()
        self.method_combo.addItem("Todos", None)
        for method in PaymentMethod.select().order_by(PaymentMethod.sort_order, PaymentMethod.name):
            self.method_combo.addItem(method.name, method.code)

    def _set_default_period(self) -> None:
        today = date.today()
        self.date_from.setDate(QDate(today.year, today.month, today.day))
        self.date_to.setDate(QDate(today.year, today.month, today.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def current_filters(self) -> DailyCollectionsFilters:
        return DailyCollectionsFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            client_id=self.client_combo.currentData(),
            movement_type=self.movement_combo.currentData(),
            payment_method=self.method_combo.currentData(),
            currency=self.currency_combo.currentData(),
            created_by=self.user_edit.text().strip() or None,
            reversals_only=self.reversals_only.isChecked(),
        )

    def clear_filters(self) -> None:
        self._set_default_period()
        self.client_combo.setCurrentIndex(0)
        self.movement_combo.setCurrentIndex(0)
        self.method_combo.setCurrentIndex(0)
        self.currency_combo.setCurrentIndex(0)
        self.user_edit.clear()
        self.reversals_only.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Cobranzas y movimientos",
                f"No se pudo generar el informe:\n{exc}",
            )
            return
        self._render_collections(result.collection_rows)
        self._render_movements(result.movement_rows)
        totals = result.totals
        self.collected_label.setText(f"Cobrado: $ {totals.collected:,.2f}")
        self.payments_label.setText(f"Recibos activos: {totals.active_payments}")
        self.clients_label.setText(f"Clientes: {totals.clients}")
        self.movements_label.setText(f"Movimientos: {totals.movements}")
        self.debit_credit_label.setText(
            f"Débitos: $ {totals.debit:,.2f} · Créditos: $ {totals.credit:,.2f}"
        )
        self.methods_label.setText(
            "Por medio: "
            + (
                " · ".join(f"{name}: $ {amount:,.2f}" for name, amount in result.collections_by_method)
                or "sin cobranzas efectivas"
            )
        )

    def _render_collections(self, rows) -> None:
        table = self.collections_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["date"].strftime("%d/%m/%Y"),
                row["receipt_number"],
                row["client_name"],
                row["amount"],
                row["payment_method_name"],
                row["reference"],
                row["order_number"] or "",
                row["carrier_name"],
                row["created_by"],
                row["status"],
                row["observations"],
            )
            for column, value in enumerate(values):
                if column == 3:
                    number = float(value or 0)
                    item = NumericTableItem(f"{number:,.2f}", number)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item = QTableWidgetItem(str(value or ""))
                if column == 2:
                    item.setData(Qt.UserRole, int(row["client_id"]))
                if column == 6 and row["order_number"] is not None:
                    item.setData(Qt.UserRole, int(row["order_number"]))
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _render_movements(self, rows) -> None:
        table = self.movements_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row["date"].strftime("%d/%m/%Y"),
                row["client_name"],
                row["movement_type"],
                row["description"],
                row["debit"],
                row["credit"],
                row["balance"],
                row["currency"],
                row["due_date"].strftime("%d/%m/%Y") if row["due_date"] else "",
                row["order_number"] or "",
                row["created_by"],
                "Sí" if row["is_reversal"] else "",
            )
            for column, value in enumerate(values):
                if column in {4, 5, 6}:
                    number = float(value or 0)
                    item = NumericTableItem(f"{number:,.2f}", number)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item = QTableWidgetItem(str(value or ""))
                if column == 1:
                    item.setData(Qt.UserRole, int(row["client_id"]))
                if column == 9 and row["order_number"] is not None:
                    item.setData(Qt.UserRole, int(row["order_number"]))
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def selected_client_id(self) -> int | None:
        table = self.collections_table if self.tabs.currentIndex() == 0 else self.movements_table
        client_column = 2 if self.tabs.currentIndex() == 0 else 1
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, client_column)
        if item is None or item.data(Qt.UserRole) is None:
            return None
        return int(item.data(Qt.UserRole))

    def selected_order_number(self) -> int | None:
        table = self.collections_table if self.tabs.currentIndex() == 0 else self.movements_table
        order_column = 6 if self.tabs.currentIndex() == 0 else 9
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, order_column)
        if item is None or item.data(Qt.UserRole) is None:
            return None
        return int(item.data(Qt.UserRole))

    def open_selected_order(self) -> None:
        order_number = self.selected_order_number()
        if order_number is None:
            QMessageBox.information(
                self, "Cobranzas y movimientos", "La fila seleccionada no tiene una orden relacionada."
            )
            return
        parent = self.parent()
        navigate = getattr(parent, "_navigate_to_route", None)
        if navigate is None:
            QMessageBox.warning(
                self, "Cobranzas y movimientos", "No se pudo abrir Órdenes de carga desde esta ventana."
            )
            return
        self.accept()
        navigate("load_orders")
        page = getattr(parent, "stack", None)
        page = page.currentWidget() if page is not None else None
        if page is None:
            return
        search_input = page.findChild(QLineEdit, "loadOrderSearchInput")
        search_button = page.findChild(QPushButton, "searchLoadOrderButton")
        if search_input is not None:
            search_input.setText(str(order_number))
            if search_button is not None:
                search_button.click()
            else:
                search_input.returnPressed.emit()

    def open_selected_client_ledger(self) -> None:
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(
                self, "Cobranzas y movimientos", "Seleccione un cliente en la grilla."
            )
            return
        callback = getattr(self.parent(), "_open_customer_ledger_for_client", None)
        if callback is None:
            QMessageBox.warning(
                self,
                "Cobranzas y movimientos",
                "No se pudo abrir la cuenta corriente desde esta ventana.",
            )
            return
        client = Client.get_by_id(client_id)
        self.accept()
        callback(client)

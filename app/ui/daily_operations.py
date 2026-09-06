from __future__ import annotations

from datetime import date, timedelta

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client
from app.reports.daily_operations import DailyOperationsFilters, DailyOperationsService


class DailyOperationsDialog(QDialog):
    DISPATCH_HEADERS = (
        "Orden",
        "Fecha",
        "Cliente",
        "Producto",
        "Cantidad",
        "Kg",
        "Importe",
        "Estado",
        "Transportista",
    )
    PENDING_HEADERS = (
        "Orden",
        "Fecha",
        "Días",
        "Cliente / destino",
        "Estado",
        "Etapa pendiente",
        "Causa",
        "Pendiente",
    )

    def __init__(self, parent=None, *, service: DailyOperationsService | None = None):
        super().__init__(parent)
        self.service = service or DailyOperationsService()
        self.setWindowTitle("Informe operativo diario")
        self.resize(1600, 850)
        self._build_ui()
        self._load_filters()
        self._month()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Informe operativo diario y estado del trabajo")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel("Qué se hizo en el período, qué quedó pendiente y dónde está trabado el trabajo."))

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.status_combo = QComboBox()
        self.client_combo = QComboBox()
        self.carrier_combo = QComboBox()
        specs = (
            ("Desde", self.date_from),
            ("Hasta", self.date_to),
            ("Estado", self.status_combo),
            ("Cliente", self.client_combo),
            ("Transportista", self.carrier_combo),
        )
        for col, (label, widget) in enumerate(specs):
            filters.addWidget(QLabel(label), 0, col)
            filters.addWidget(widget, 1, col)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        today = QPushButton("Hoy")
        today.clicked.connect(self._today)
        yesterday = QPushButton("Ayer")
        yesterday.clicked.connect(self._yesterday)
        week = QPushButton("Últimos 7 días")
        week.clicked.connect(self._week)
        month = QPushButton("Este mes")
        month.clicked.connect(self._month)
        open_order = QPushButton("Abrir orden")
        open_order.clicked.connect(self.open_selected_order)
        for button in (consult, today, yesterday, week, month, open_order):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QGridLayout()
        self.summary_labels = [QLabel() for _ in range(12)]
        for index, label in enumerate(self.summary_labels):
            label.setStyleSheet("font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;")
            summary.addWidget(label, index // 6, index % 6)
        root.addLayout(summary)

        self.tabs = QTabWidget()
        self.dispatch_table = QTableWidget(0, len(self.DISPATCH_HEADERS))
        self.dispatch_table.setHorizontalHeaderLabels(self.DISPATCH_HEADERS)
        self._setup_table(self.dispatch_table)
        self.dispatch_table.doubleClicked.connect(lambda *_: self.open_selected_order())
        self.pending_table = QTableWidget(0, len(self.PENDING_HEADERS))
        self.pending_table.setHorizontalHeaderLabels(self.PENDING_HEADERS)
        self._setup_table(self.pending_table)
        self.pending_table.doubleClicked.connect(lambda *_: self.open_selected_order())
        self.tabs.addTab(self.dispatch_table, "Despachos del período")
        self.tabs.addTab(self.pending_table, "Órdenes pendientes")
        root.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    @staticmethod
    def _setup_table(table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSortingEnabled(True)

    def _load_filters(self):
        self.status_combo.addItem("Todos", None)
        for status in (
            LoadOrder.STATUS_PENDING,
            LoadOrder.STATUS_ISSUED,
            LoadOrder.STATUS_CLOSED,
            LoadOrder.STATUS_ANNULLED,
        ):
            self.status_combo.addItem(status, status)
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        self.carrier_combo.addItem("Todos", None)
        for carrier in Carrier.select().order_by(Carrier.name):
            self.carrier_combo.addItem(carrier.name, carrier.id)

    @staticmethod
    def _to_qdate(value: date) -> QDate:
        return QDate(value.year, value.month, value.day)

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _set_range(self, start: date, end: date) -> None:
        self.date_from.setDate(self._to_qdate(start))
        self.date_to.setDate(self._to_qdate(end))
        self.refresh()

    def _today(self):
        current = date.today()
        self._set_range(current, current)

    def _yesterday(self):
        current = date.today() - timedelta(days=1)
        self._set_range(current, current)

    def _week(self):
        current = date.today()
        self._set_range(current - timedelta(days=6), current)

    def _month(self):
        current = date.today()
        self._set_range(current.replace(day=1), current)

    def current_filters(self) -> DailyOperationsFilters:
        return DailyOperationsFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            status=self.status_combo.currentData(),
            client_id=self.client_combo.currentData(),
            carrier_id=self.carrier_combo.currentData(),
        )

    def refresh(self):
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Informe operativo", f"No se pudo generar el informe:\n{exc}")
            return
        totals = result.totals
        values = (
            f"Creadas: {totals.created}",
            f"Cerradas: {totals.closed}",
            f"Anuladas: {totals.annulled}",
            f"Abiertas: {totals.open_orders}",
            f"> 7 días: {totals.over_7_days}",
            f"Mercadería pendiente: {totals.incomplete_merchandise}",
            f"Despachado: $ {totals.dispatched_total:,.2f}",
            f"Despachado: {totals.dispatched_tonnes:,.3f} TN",
            f"Clientes atendidos: {totals.clients_served}",
            f"Cobrado: $ {totals.collected:,.2f}",
            f"Recibos: {totals.collection_payments}",
            f"Déb./Créd. manual: $ {totals.manual_debit:,.2f} / $ {totals.manual_credit:,.2f}",
        )
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        self._render_dispatch(result.dispatch_rows)
        self._render_pending(result.pending_rows)

    def _render_dispatch(self, rows):
        self.dispatch_table.setSortingEnabled(False)
        self.dispatch_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row["order_number"],
                row["date"].strftime("%d/%m/%Y"),
                row["client_name"],
                row["product_name"],
                row["quantity"],
                row["kilos"],
                f"{row['total']:,.2f}",
                row["status"],
                row["carrier_name"],
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {0, 4, 5}:
                    item.setData(Qt.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole + 1, int(row["order_number"]))
                self.dispatch_table.setItem(r, c, item)
        self.dispatch_table.resizeColumnsToContents()
        self.dispatch_table.setSortingEnabled(True)

    def _render_pending(self, rows):
        self.pending_table.setSortingEnabled(False)
        self.pending_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row["order_number"],
                row["date"].strftime("%d/%m/%Y"),
                row["age_days"],
                row["destinations"] or row["client_name"],
                row["status"],
                row["pending_stage"],
                row["pending_reason"],
                row["pending_quantity"],
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {0, 2, 7}:
                    item.setData(Qt.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole + 1, int(row["order_number"]))
                self.pending_table.setItem(r, c, item)
        self.pending_table.resizeColumnsToContents()
        self.pending_table.setSortingEnabled(True)

    def _active_table(self) -> QTableWidget:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, QTableWidget) else self.dispatch_table

    def selected_order_number(self) -> int | None:
        table = self._active_table()
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole + 1)
        return int(value) if value is not None else None

    def open_selected_order(self):
        order_number = self.selected_order_number()
        if order_number is None:
            QMessageBox.information(self, "Informe operativo", "Seleccione una orden.")
            return
        parent = self.parent()
        navigate = getattr(parent, "_navigate_to_route", None)
        if navigate is None:
            QMessageBox.warning(self, "Informe operativo", "No se pudo abrir Órdenes de carga.")
            return
        self.accept()
        navigate("load_orders")
        stack = getattr(parent, "stack", None)
        page = stack.currentWidget() if stack is not None else None
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

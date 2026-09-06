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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Client, Product
from app.reports.lot_traceability import LotTraceabilityFilters, LotTraceabilityService


class LotTraceabilityDialog(QDialog):
    HEADERS = (
        "Lote",
        "Elaboración",
        "Producto",
        "Cliente",
        "Destino",
        "Orden",
        "Despacho",
        "Pallet",
        "Cantidad",
        "Kg",
        "Estado",
        "Transportista",
    )

    def __init__(self, parent=None, *, service: LotTraceabilityService | None = None):
        super().__init__(parent)
        self.service = service or LotTraceabilityService()
        self.setWindowTitle("Trazabilidad por lote")
        self.resize(1600, 850)
        self._build_ui()
        self._load_filters()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Trazabilidad por lote, cliente y pallet")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel("Qué clientes recibieron cada lote, en qué órdenes, pallets y fechas."))

        filters = QGridLayout()
        self.lote_input = QLineEdit()
        self.lote_input.setPlaceholderText("Ej. L-2026-DEMO-01")
        self.elab_from = QDateEdit(calendarPopup=True)
        self.elab_to = QDateEdit(calendarPopup=True)
        self.elab_from.setDisplayFormat("dd/MM/yyyy")
        self.elab_to.setDisplayFormat("dd/MM/yyyy")
        self.elab_from.setSpecialValueText(" ")
        self.elab_to.setSpecialValueText(" ")
        self.client_combo = QComboBox()
        self.product_combo = QComboBox()
        self.dispatch_from = QDateEdit(calendarPopup=True)
        self.dispatch_to = QDateEdit(calendarPopup=True)
        self.dispatch_from.setDisplayFormat("dd/MM/yyyy")
        self.dispatch_to.setDisplayFormat("dd/MM/yyyy")
        self.order_number = QSpinBox()
        self.order_number.setRange(0, 99999999)
        self.order_number.setSpecialValueText("Todas")
        self.status_combo = QComboBox()
        specs = (
            ("Lote", self.lote_input),
            ("Elab. desde", self.elab_from),
            ("Elab. hasta", self.elab_to),
            ("Cliente", self.client_combo),
            ("Producto", self.product_combo),
            ("Despacho desde", self.dispatch_from),
            ("Despacho hasta", self.dispatch_to),
            ("Orden", self.order_number),
            ("Estado", self.status_combo),
        )
        for col, (label, widget) in enumerate(specs):
            filters.addWidget(QLabel(label), 0, col)
            filters.addWidget(widget, 1, col)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self.clear_filters)
        open_order = QPushButton("Ver orden")
        open_order.clicked.connect(self.open_selected_order)
        for button in (consult, clear, open_order):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.summary_labels = [QLabel() for _ in range(6)]
        for label in self.summary_labels:
            label.setStyleSheet("font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;")
            summary.addWidget(label)
        summary.addStretch(1)
        root.addLayout(summary)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(lambda *_: self.open_selected_order())
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _load_filters(self):
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        self.product_combo.addItem("Todos", None)
        for product in Product.select().order_by(Product.name):
            self.product_combo.addItem(product.name, product.id)
        self.status_combo.addItem("Todos (sin anuladas)", None)
        for status in (
            LoadOrder.STATUS_PENDING,
            LoadOrder.STATUS_ISSUED,
            LoadOrder.STATUS_CLOSED,
            LoadOrder.STATUS_ANNULLED,
        ):
            self.status_combo.addItem(status, status)
        today = date.today()
        start = today - timedelta(days=90)
        self.dispatch_from.setDate(QDate(start.year, start.month, start.day))
        self.dispatch_to.setDate(QDate(today.year, today.month, today.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def clear_filters(self):
        self.lote_input.clear()
        self.client_combo.setCurrentIndex(0)
        self.product_combo.setCurrentIndex(0)
        self.order_number.setValue(0)
        self.status_combo.setCurrentIndex(0)
        self.refresh()

    def current_filters(self) -> LotTraceabilityFilters:
        lote = self.lote_input.text().strip() or None
        order_number = self.order_number.value() or None
        return LotTraceabilityFilters(
            lote=lote,
            client_id=self.client_combo.currentData(),
            product_id=self.product_combo.currentData(),
            dispatch_from=self._py_date(self.dispatch_from),
            dispatch_to=self._py_date(self.dispatch_to),
            order_number=order_number,
            status=self.status_combo.currentData(),
        )

    def refresh(self):
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Trazabilidad", f"No se pudo generar la consulta:\n{exc}")
            return
        totals = result.totals
        date_range = ""
        if totals.first_dispatch and totals.last_dispatch:
            date_range = f"{totals.first_dispatch.strftime('%d/%m/%Y')} - {totals.last_dispatch.strftime('%d/%m/%Y')}"
        values = (
            f"Cantidad: {totals.dispatched_quantity:,.3f}",
            f"Kg: {totals.dispatched_kilos:,.3f}",
            f"Clientes: {totals.clients}",
            f"Destinos: {totals.destinations}",
            f"Órdenes: {totals.orders}",
            f"Rango: {date_range}",
        )
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        self._render_rows(result.rows)

    def _render_rows(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            elab = row["elaboration_date"].strftime("%d/%m/%Y") if row["elaboration_date"] else "-"
            values = (
                row["lote"],
                elab,
                row["product_name"],
                row["client_name"],
                row["destination"],
                row["order_number"],
                row["dispatch_date"].strftime("%d/%m/%Y"),
                row["pallet"],
                row["quantity"],
                row["kilos"],
                row["order_status"],
                row["carrier_name"],
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {5, 8, 9}:
                    item.setData(Qt.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 5:
                    item.setData(Qt.UserRole + 1, int(row["order_number"]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def selected_order_number(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 5)
        if item is None:
            return None
        value = item.data(Qt.UserRole + 1)
        return int(value) if value is not None else None

    def open_selected_order(self):
        order_number = self.selected_order_number()
        if order_number is None:
            QMessageBox.information(self, "Trazabilidad", "Seleccione una fila.")
            return
        parent = self.parent()
        navigate = getattr(parent, "_navigate_to_route", None)
        if navigate is None:
            QMessageBox.warning(self, "Trazabilidad", "No se pudo abrir Órdenes de carga.")
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

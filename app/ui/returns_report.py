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
from app.reports.returns_report import ReturnsFilters, ReturnsReportService


class ReturnsReportDialog(QDialog):
    HEADERS = (
        "Fecha",
        "Cliente",
        "Destino",
        "Orden",
        "Producto",
        "Lote",
        "Elab.",
        "Despachada",
        "Devuelta",
        "Unidad",
        "Kg",
        "Motivo",
        "Importe original",
        "Crédito",
        "Resolución",
    )

    def __init__(self, parent=None, *, service: ReturnsReportService | None = None):
        super().__init__(parent)
        self.service = service or ReturnsReportService()
        self.setWindowTitle("Devoluciones y reclamos")
        self.resize(1600, 850)
        self._build_ui()
        self._load_filters()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Devoluciones, reclamos y análisis por lote")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel("Incidencias por cliente, producto y lote, con bruto, devuelto y neto auditables."))

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.client_combo = QComboBox()
        self.product_combo = QComboBox()
        self.lote_input = QLineEdit()
        self.lote_input.setPlaceholderText("Lote exacto")
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Motivo contiene")
        self.status_combo = QComboBox()
        self.order_number = QSpinBox()
        self.order_number.setRange(0, 99999999)
        self.order_number.setSpecialValueText("Todas")
        specs = (
            ("Desde", self.date_from),
            ("Hasta", self.date_to),
            ("Cliente", self.client_combo),
            ("Producto", self.product_combo),
            ("Lote", self.lote_input),
            ("Motivo", self.reason_input),
            ("Estado", self.status_combo),
            ("Orden", self.order_number),
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
        traceability = QPushButton("Ver trazabilidad del lote")
        traceability.clicked.connect(self.open_lot_traceability)
        for button in (consult, clear, open_order, traceability):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QGridLayout()
        self.summary_labels = [QLabel() for _ in range(8)]
        for index, label in enumerate(self.summary_labels):
            label.setStyleSheet("font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;")
            summary.addWidget(label, index // 4, index % 4)
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
        self.status_combo.addItem("Todos", None)
        for status in (
            LoadOrder.STATUS_PENDING,
            LoadOrder.STATUS_ISSUED,
            LoadOrder.STATUS_CLOSED,
            LoadOrder.STATUS_ANNULLED,
        ):
            self.status_combo.addItem(status, status)
        today = date.today()
        start = today - timedelta(days=90)
        self.date_from.setDate(QDate(start.year, start.month, start.day))
        self.date_to.setDate(QDate(today.year, today.month, today.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def clear_filters(self):
        self.client_combo.setCurrentIndex(0)
        self.product_combo.setCurrentIndex(0)
        self.lote_input.clear()
        self.reason_input.clear()
        self.status_combo.setCurrentIndex(0)
        self.order_number.setValue(0)
        self.refresh()

    def current_filters(self) -> ReturnsFilters:
        return ReturnsFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            client_id=self.client_combo.currentData(),
            product_id=self.product_combo.currentData(),
            lote=self.lote_input.text().strip() or None,
            reason=self.reason_input.text().strip() or None,
            status=self.status_combo.currentData(),
            order_number=self.order_number.value() or None,
        )

    def refresh(self):
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Devoluciones", f"No se pudo generar el informe:\n{exc}")
            return
        totals = result.totals
        rate = f"{totals.return_rate_percent:.2f} %" if totals.return_rate_percent is not None else "-"
        values = (
            f"Devoluciones: {totals.returns}",
            f"Cant. devuelta: {totals.returned_quantity:,.3f}",
            f"Kg devueltos: {totals.returned_kilos:,.3f}",
            f"Crédito: $ {totals.credited_amount:,.2f}",
            f"Bruto despachado: $ {totals.dispatched_gross:,.2f}",
            f"Neto: $ {totals.net_amount:,.2f}",
            f"% devuelto: {rate}",
            f"Top cliente: {result.top_clients[0]['name']}" if result.top_clients else "Top cliente: -",
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
                row["return_date"].strftime("%d/%m/%Y"),
                row["client_name"],
                row["destination"],
                row["order_number"],
                row["product_name"],
                row["lote"],
                elab,
                row["dispatched_quantity"],
                row["returned_quantity"],
                row["unit"],
                row["kilos"],
                row["reason"],
                f"{row['original_total']:,.2f}",
                f"{row['credit_amount']:,.2f}",
                row["resolution"],
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {3, 7, 8, 10}:
                    item.setData(Qt.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 3:
                    item.setData(Qt.UserRole + 1, int(row["order_number"]))
                if c == 5 and row["lote"]:
                    item.setData(Qt.UserRole + 1, row["lote"])
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def selected_order_number(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 3)
        if item is None:
            return None
        value = item.data(Qt.UserRole + 1)
        return int(value) if value is not None else None

    def selected_lote(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return self.lote_input.text().strip() or None
        item = self.table.item(row, 5)
        if item is None:
            return None
        value = item.data(Qt.UserRole + 1) or self.lote_input.text().strip()
        return value or None

    def open_selected_order(self):
        order_number = self.selected_order_number()
        if order_number is None:
            QMessageBox.information(self, "Devoluciones", "Seleccione una fila.")
            return
        parent = self.parent()
        navigate = getattr(parent, "_navigate_to_route", None)
        if navigate is None:
            QMessageBox.warning(self, "Devoluciones", "No se pudo abrir Órdenes de carga.")
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

    def open_lot_traceability(self):
        lote = self.selected_lote()
        if not lote:
            QMessageBox.information(self, "Devoluciones", "Seleccione una fila con lote.")
            return
        from app.ui.lot_traceability import LotTraceabilityDialog

        dialog = LotTraceabilityDialog(self.parent())
        dialog.lote_input.setText(lote)
        dialog.refresh()
        dialog.exec_()

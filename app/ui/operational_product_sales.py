from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Client, Product
from app.reports.managerial_sales_dispatch import SalesDispatchFilters
from app.reports.operational_product_sales import OperationalProductSalesService


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


class OperationalProductSalesDialog(QDialog):
    SUMMARY_HEADERS = (
        "Producto",
        "Cantidad",
        "Unidad",
        "Kg",
        "TN",
        "Neto",
        "IVA",
        "Total",
        "Órdenes",
    )
    DETAIL_HEADERS = (
        "Fecha",
        "Orden",
        "Cliente",
        "Destino",
        "Producto",
        "Cantidad",
        "Unidad",
        "Kg",
        "TN",
        "Precio neto",
        "Neto",
        "IVA",
        "Total",
        "Estado",
        "Transportista",
    )

    def __init__(self, parent=None, *, service: OperationalProductSalesService | None = None):
        super().__init__(parent)
        self.service = service or OperationalProductSalesService()
        self._last_result = None
        self.setWindowTitle("Informe operativo · Ventas por producto")
        self.resize(1480, 820)
        self._build_ui()
        self._load_filters()
        self._set_default_period()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("Ventas por producto")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        subtitle = QLabel(
            "Consulta operativa por rango de fechas. Por defecto incluye órdenes Pendiente, Emitida y Cerrada."
        )
        subtitle.setStyleSheet("color:#64748b;")
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.product_combo = QComboBox()
        self.client_combo = QComboBox()
        self.status_combo = QComboBox()

        for column, (label, widget) in enumerate(
            (
                ("Desde", self.date_from),
                ("Hasta", self.date_to),
                ("Producto", self.product_combo),
                ("Cliente", self.client_combo),
                ("Estado", self.status_combo),
            )
        ):
            filters.addWidget(QLabel(label), 0, column)
            filters.addWidget(widget, 1, column)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar filtros")
        clear.clicked.connect(self.clear_filters)
        export = QPushButton("Exportar a Excel")
        export.clicked.connect(self.export_excel)
        actions.addWidget(consult)
        actions.addWidget(clear)
        actions.addWidget(export)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.total_label = QLabel()
        self.tonnes_label = QLabel()
        self.products_label = QLabel()
        self.orders_label = QLabel()
        for label in (
            self.total_label,
            self.tonnes_label,
            self.products_label,
            self.orders_label,
        ):
            label.setStyleSheet(
                "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
                "border-radius:8px;padding:8px 12px;"
            )
            summary.addWidget(label)
        summary.addStretch(1)
        root.addLayout(summary)

        self.tabs = QTabWidget()
        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        self.summary_table = self._table(self.SUMMARY_HEADERS)
        summary_layout.addWidget(self.summary_table, 1)

        detail_tab = QWidget()
        detail_layout = QVBoxLayout(detail_tab)
        self.detail_table = self._table(self.DETAIL_HEADERS)
        detail_layout.addWidget(self.detail_table, 1)

        self.tabs.addTab(summary_tab, "Resumen por producto")
        self.tabs.addTab(detail_tab, "Detalle de ventas")
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
        self.product_combo.clear()
        self.product_combo.addItem("Todos", None)
        for product in Product.select().order_by(Product.name):
            self.product_combo.addItem(product.name, product.id)

        self.client_combo.clear()
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)

        self.status_combo.clear()
        self.status_combo.addItem("Órdenes vigentes (Pendiente + Emitida + Cerrada)", None)
        self.status_combo.addItem("Pendiente", LoadOrder.STATUS_PENDING)
        self.status_combo.addItem("Emitida", LoadOrder.STATUS_ISSUED)
        self.status_combo.addItem("Cerrada", LoadOrder.STATUS_CLOSED)
        self.status_combo.addItem("Todos los estados", "__all__")

    def _set_default_period(self) -> None:
        today = date.today()
        self.date_from.setDate(QDate(today.year, today.month, 1))
        self.date_to.setDate(QDate(today.year, today.month, today.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _selected_statuses(self) -> tuple[str, ...] | None:
        value = self.status_combo.currentData()
        if value is None:
            return None
        if value == "__all__":
            return (
                LoadOrder.STATUS_PENDING,
                LoadOrder.STATUS_LEGACY_DRAFT,
                LoadOrder.STATUS_ISSUED,
                LoadOrder.STATUS_CLOSED,
                LoadOrder.STATUS_ANNULLED,
            )
        return (str(value),)

    def current_filters(self) -> SalesDispatchFilters:
        return SalesDispatchFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            client_id=self.client_combo.currentData(),
            product_id=self.product_combo.currentData(),
            statuses=self._selected_statuses(),
            sort_by="product",
        )

    def clear_filters(self) -> None:
        self._set_default_period()
        self.product_combo.setCurrentIndex(0)
        self.client_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.refresh()

    def refresh(self) -> None:
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ventas por producto",
                f"No se pudo generar el informe:\n{exc}",
            )
            return
        self._last_result = result
        self._render_summary(result)
        self._render_detail(result)
        self.total_label.setText(f"Venta total: $ {result.total:,.2f}")
        self.tonnes_label.setText(f"TN: {result.tonnes:,.3f}")
        self.products_label.setText(f"Productos: {result.products}")
        self.orders_label.setText(f"Órdenes: {result.orders}")

    def _render_summary(self, result) -> None:
        table = self.summary_table
        table.setSortingEnabled(False)
        table.setRowCount(len(result.summary_rows))
        for row_index, row in enumerate(result.summary_rows):
            values = (
                row.product_name,
                row.quantity,
                row.unit,
                row.kilos,
                row.tonnes,
                row.net,
                row.vat,
                row.total,
                row.orders,
            )
            for column, value in enumerate(values):
                if column in {1, 3, 4, 5, 6, 7, 8}:
                    number = float(value or 0)
                    decimals = 3 if column in {1, 3, 4} else (0 if column == 8 else 2)
                    item = NumericTableItem(f"{number:,.{decimals}f}", number)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item = QTableWidgetItem(str(value or ""))
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _render_detail(self, result) -> None:
        table = self.detail_table
        table.setSortingEnabled(False)
        table.setRowCount(len(result.detail.rows))
        for row_index, row in enumerate(result.detail.rows):
            values = (
                row["date"].strftime("%d/%m/%Y"),
                row["order_number"],
                row["client_name"],
                row["destination"],
                row["product_name"],
                row["quantity"],
                row["unit"],
                row["kilos"],
                row["tonnes"],
                row["unit_net_price"],
                row["net"],
                row["vat"],
                row["total"],
                row["status"],
                row["carrier_name"],
            )
            for column, value in enumerate(values):
                if column == 1:
                    item = NumericTableItem(str(value), int(value))
                elif column in {5, 7, 8, 9, 10, 11, 12}:
                    number = float(value or 0)
                    decimals = 3 if column in {5, 7, 8} else 2
                    item = NumericTableItem(f"{number:,.{decimals}f}", number)
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    item = QTableWidgetItem(str(value or ""))
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def export_excel(self) -> None:
        if self._last_result is None:
            self.refresh()
        if self._last_result is None:
            return
        filters = self._last_result.filters
        default_name = f"ventas_productos_{filters.start.isoformat()}_{filters.end.isoformat()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar ventas por producto",
            str(Path.home() / default_name),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            exported = self.service.export_xlsx(self._last_result, path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Exportar a Excel",
                f"No se pudo generar el archivo Excel:\n{exc}",
            )
            return
        QMessageBox.information(
            self,
            "Exportar a Excel",
            f"Archivo generado correctamente:\n{exported}",
        )

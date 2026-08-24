from __future__ import annotations

from datetime import date

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
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, Product
from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)


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


class ManagerialSalesDispatchDialog(QDialog):
    HEADERS = (
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

    def __init__(self, parent=None, *, service: ManagerialSalesDispatchService | None = None):
        super().__init__(parent)
        self.service = service or ManagerialSalesDispatchService()
        self.setWindowTitle("Informe gerencial · Ventas y despachos")
        self.resize(1460, 760)
        self._build_ui()
        self._load_filter_options()
        self._set_default_period()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Ventas y despachos")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel(
            "Detalle auditable de los despachos valorizados. Por defecto muestra órdenes Cerradas, igual que el Dashboard Gerencial."
        )
        subtitle.setStyleSheet("color: #64748b;")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)

        dashboard = QPushButton("Abrir Dashboard Gerencial")
        dashboard.setToolTip("Abrir el resumen gerencial en HTML")
        dashboard.clicked.connect(self.open_managerial_dashboard)
        header.addWidget(dashboard, 0, Qt.AlignTop)
        root.addLayout(header)

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.client_combo = QComboBox()
        self.product_combo = QComboBox()
        self.carrier_combo = QComboBox()
        self.status_combo = QComboBox()
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText("Ciudad o dirección")

        filters.addWidget(QLabel("Desde"), 0, 0)
        filters.addWidget(self.date_from, 1, 0)
        filters.addWidget(QLabel("Hasta"), 0, 1)
        filters.addWidget(self.date_to, 1, 1)
        filters.addWidget(QLabel("Cliente"), 0, 2)
        filters.addWidget(self.client_combo, 1, 2)
        filters.addWidget(QLabel("Producto"), 0, 3)
        filters.addWidget(self.product_combo, 1, 3)
        filters.addWidget(QLabel("Transportista"), 0, 4)
        filters.addWidget(self.carrier_combo, 1, 4)
        filters.addWidget(QLabel("Estado"), 0, 5)
        filters.addWidget(self.status_combo, 1, 5)
        filters.addWidget(QLabel("Destino"), 0, 6)
        filters.addWidget(self.destination_edit, 1, 6)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar filtros")
        clear.clicked.connect(self.clear_filters)
        actions.addWidget(consult)
        actions.addWidget(clear)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.total_label = QLabel()
        self.tonnes_label = QLabel()
        self.orders_label = QLabel()
        self.lines_label = QLabel()
        for label in (self.total_label, self.tonnes_label, self.orders_label, self.lines_label):
            label.setStyleSheet(
                "font-weight: 700; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px;"
            )
            summary.addWidget(label)
        summary.addStretch(1)
        root.addLayout(summary)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)

        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def open_managerial_dashboard(self) -> None:
        try:
            ManagerialDashboardHtmlReport().open()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Dashboard Gerencial",
                f"No se pudo abrir el Dashboard Gerencial:\n{exc}",
            )

    def _load_filter_options(self) -> None:
        self._fill_combo(self.client_combo, "Todos", Client.select().order_by(Client.name), lambda item: item.name)
        self._fill_combo(self.product_combo, "Todos", Product.select().order_by(Product.name), lambda item: item.name)
        self._fill_combo(self.carrier_combo, "Todos", Carrier.select().order_by(Carrier.name), lambda item: item.name)

        self.status_combo.clear()
        self.status_combo.addItem("Despachos efectivos (Cerrada)", None)
        self.status_combo.addItem("Todos los estados", "__all__")
        for status in (
            LoadOrder.STATUS_PENDING,
            LoadOrder.STATUS_LEGACY_DRAFT,
            LoadOrder.STATUS_ISSUED,
            LoadOrder.STATUS_CLOSED,
            LoadOrder.STATUS_ANNULLED,
        ):
            self.status_combo.addItem(status, status)

    @staticmethod
    def _fill_combo(combo: QComboBox, empty_label: str, query, label_getter) -> None:
        combo.clear()
        combo.addItem(empty_label, None)
        for item in query:
            combo.addItem(label_getter(item), item.id)

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
            carrier_id=self.carrier_combo.currentData(),
            statuses=self._selected_statuses(),
            destination=self.destination_edit.text().strip() or None,
            sort_by="date",
        )

    def clear_filters(self) -> None:
        self._set_default_period()
        self.client_combo.setCurrentIndex(0)
        self.product_combo.setCurrentIndex(0)
        self.carrier_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.destination_edit.clear()
        self.refresh()

    def refresh(self) -> None:
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Ventas y despachos", f"No se pudo generar el informe:\n{exc}")
            return
        self._render_result(result)

    def _render_result(self, result) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
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
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

        totals = result.totals
        self.total_label.setText(f"Total: $ {totals.total:,.2f}")
        self.tonnes_label.setText(f"TN: {totals.tonnes:,.3f}")
        self.orders_label.setText(f"Órdenes: {totals.orders}")
        self.lines_label.setText(f"Renglones: {totals.lines}")

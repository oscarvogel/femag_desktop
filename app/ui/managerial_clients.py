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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from app.models.masters import Client
from app.reports.daily_collections import DailyCollectionsFilters, DailyCollectionsReportService
from app.reports.lot_traceability import LotTraceabilityFilters, LotTraceabilityService
from app.reports.managerial_clients import ManagerialClientsFilters, ManagerialClientsService
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)
from app.reports.returns_report import ReturnsFilters, ReturnsReportService


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _short(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


class ManagerialClientsDialog(QDialog):
    HEADERS = (
        "Cliente",
        "Facturación",
        "TN",
        "Órdenes",
        "Ticket prom.",
        "Último despacho",
        "Días sin despacho",
        "Último pago",
        "Saldo",
        "Deuda vencida",
        "Días atraso",
        "Devoluciones",
        "Lotes",
        "Estado comercial",
    )

    SORTS = (
        ("Facturación", "total"),
        ("Toneladas", "tonnes"),
        ("Saldo", "balance"),
        ("Deuda vencida", "overdue"),
        ("Días sin despacho", "idle"),
        ("Nombre", "name"),
    )

    def __init__(self, parent=None, *, service: ManagerialClientsService | None = None):
        super().__init__(parent)
        self.service = service or ManagerialClientsService()
        self.setWindowTitle("Informe gerencial de clientes")
        self.resize(1700, 850)
        self._build_ui()
        self._load_filters()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Informe gerencial de clientes")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel("Actividad comercial, situación financiera y seguimiento por cliente."))

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.client_combo = QComboBox()
        self.activity_combo = QComboBox()
        self.sort_combo = QComboBox()
        self.min_idle = QSpinBox()
        self.min_idle.setRange(0, 3650)
        self.min_idle.setSuffix(" días")
        self.overdue_only = QCheckBox("Con deuda vencida")
        self.balance_only = QCheckBox("Con saldo")
        self.returns_only = QCheckBox("Con devoluciones")
        self.lots_only = QCheckBox("Con lotes")
        specs = (
            ("Desde", self.date_from),
            ("Hasta", self.date_to),
            ("Cliente", self.client_combo),
            ("Actividad", self.activity_combo),
            ("Ordenar por", self.sort_combo),
            ("Más de N días sin despacho", self.min_idle),
        )
        for col, (label, widget) in enumerate(specs):
            filters.addWidget(QLabel(label), 0, col)
            filters.addWidget(widget, 1, col)
        flags = QHBoxLayout()
        for widget in (self.overdue_only, self.balance_only, self.returns_only, self.lots_only):
            flags.addWidget(widget)
        flags.addStretch(1)
        root.addLayout(filters)
        root.addLayout(flags)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        month = QPushButton("Este mes")
        month.clicked.connect(self._month)
        year = QPushButton("Este año")
        year.clicked.connect(self._year)
        history = QPushButton("Histórico del cliente")
        history.clicked.connect(self.open_history)
        ledger = QPushButton("Cuenta corriente")
        ledger.clicked.connect(self.open_ledger)
        traceability = QPushButton("Lotes del cliente")
        traceability.clicked.connect(self.open_traceability)
        returns = QPushButton("Devoluciones")
        returns.clicked.connect(self.open_returns)
        for button in (consult, month, year, history, ledger, traceability, returns):
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
        self.table.doubleClicked.connect(lambda *_: self.open_history())
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
        self.activity_combo.addItem("Todos", None)
        self.activity_combo.addItem("Con actividad", "with")
        self.activity_combo.addItem("Sin actividad", "without")
        for label, key in self.SORTS:
            self.sort_combo.addItem(label, key)
        today = date.today()
        self.date_from.setDate(QDate(today.year, 1, 1))
        self.date_to.setDate(QDate(today.year, today.month, today.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _month(self):
        today = date.today()
        self.date_from.setDate(QDate(today.year, today.month, 1))
        self.date_to.setDate(QDate(today.year, today.month, today.day))
        self.refresh()

    def _year(self):
        today = date.today()
        self.date_from.setDate(QDate(today.year, 1, 1))
        self.date_to.setDate(QDate(today.year, today.month, today.day))
        self.refresh()

    def current_filters(self) -> ManagerialClientsFilters:
        return ManagerialClientsFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            client_id=self.client_combo.currentData(),
            activity=self.activity_combo.currentData(),
            min_idle_days=self.min_idle.value(),
            has_overdue=self.overdue_only.isChecked(),
            has_balance=self.balance_only.isChecked(),
            has_returns=self.returns_only.isChecked(),
            has_lots=self.lots_only.isChecked(),
            sort_by=self.sort_combo.currentData(),
        )

    def refresh(self):
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Clientes", f"No se pudo generar el informe:\n{exc}")
            return
        totals = result.totals
        values = (
            f"Clientes: {totals.clients}",
            f"Con actividad: {totals.with_activity}",
            f"Sin actividad: {totals.without_activity}",
            f"Nuevos: {totals.new_clients} / Recuperados: {totals.recovered_clients}",
            f"Facturación: $ {_money(totals.total)}",
            f"Deuda vencida: $ {_money(totals.overdue)}",
        )
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        self._rows = list(result.rows)
        self._render_rows(self._rows)

    @staticmethod
    def _commercial_state(row: dict) -> str:
        if row["is_new"]:
            return "Nuevo"
        if row["recovered"]:
            return "Recuperado"
        if not row["has_activity"]:
            return "Sin actividad"
        if row["idle"]:
            return "Inactivo"
        return "Activo"

    def _render_rows(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row["client_name"],
                _money(row["period_total"]),
                f"{row['period_tonnes']:,.3f}",
                row["period_orders"],
                _money(row["average_ticket"]),
                _short(row["last_dispatch"]),
                row["days_since_dispatch"] if row["days_since_dispatch"] is not None else "-",
                _short(row["last_payment"]),
                _money(row["balance"]),
                _money(row["overdue"]),
                row["days_overdue"] if row["days_overdue"] is not None else "-",
                row["returns_count"],
                row["distinct_lots"],
                self._commercial_state(row),
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {1, 2, 3, 4, 8, 9}:
                    item.setData(Qt.UserRole, float(str(value).replace(",", "")))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole + 1, int(row["client_id"]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def selected_client_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return None
        return int(self._rows[row]["client_id"])

    def selected_client_name(self) -> str:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return ""
        return str(self._rows[row]["client_name"])

    def open_history(self):
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(self, "Clientes", "Seleccione un cliente.")
            return
        dialog = ClientHistoryDialog(
            self, client_id=client_id, client_name=self.selected_client_name(),
            start=self._py_date(self.date_from), end=self._py_date(self.date_to),
        )
        dialog.exec_()

    def open_ledger(self):
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(self, "Clientes", "Seleccione un cliente.")
            return
        from app.models.masters import Client as ClientModel

        parent = self.parent()
        opener = getattr(parent, "_open_customer_ledger_for_client", None)
        if opener is None:
            QMessageBox.warning(self, "Clientes", "No se pudo abrir la cuenta corriente.")
            return
        self.accept()
        opener(ClientModel.get_by_id(client_id))

    def open_traceability(self):
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(self, "Clientes", "Seleccione un cliente.")
            return
        from app.ui.lot_traceability import LotTraceabilityDialog

        dialog = LotTraceabilityDialog(self.parent())
        for index in range(dialog.client_combo.count()):
            if dialog.client_combo.itemData(index) == client_id:
                dialog.client_combo.setCurrentIndex(index)
                break
        dialog.refresh()
        dialog.exec_()

    def open_returns(self):
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(self, "Clientes", "Seleccione un cliente.")
            return
        from app.ui.returns_report import ReturnsReportDialog

        dialog = ReturnsReportDialog(self.parent())
        for index in range(dialog.client_combo.count()):
            if dialog.client_combo.itemData(index) == client_id:
                dialog.client_combo.setCurrentIndex(index)
                break
        dialog.refresh()
        dialog.exec_()


class ClientHistoryDialog(QDialog):
    def __init__(self, parent, *, client_id: int, client_name: str, start: date, end: date):
        super().__init__(parent)
        self.client_id = client_id
        self.start = start
        self.end = end
        self.setWindowTitle(f"Histórico - {client_name}")
        self.resize(1400, 750)
        root = QVBoxLayout(self)
        title = QLabel(f"Histórico integral - {client_name}")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel(f"Período: {_short(start)} - {_short(end)}"))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_tabs()
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _make_table(self, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSortingEnabled(True)
        return table

    @staticmethod
    def _fill(table: QTableWidget, rows: list[tuple]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _build_tabs(self):
        dispatch = ManagerialSalesDispatchService().report(
            SalesDispatchFilters(start=self.start, end=self.end, client_id=self.client_id)
        )
        table = self._make_table(("Fecha", "Orden", "Producto", "Cantidad", "Kg", "Importe", "Estado"))
        self._fill(
            table,
            [
                (
                    _short(row["date"]), row["order_number"], row["product_name"],
                    row["quantity"], row["kilos"], _money(row["total"]), row["status"],
                )
                for row in dispatch.rows
            ],
        )
        self.tabs.addTab(table, f"Despachos ({len(dispatch.rows)})")

        movements = DailyCollectionsReportService().report(
            DailyCollectionsFilters(start=self.start, end=self.end, client_id=self.client_id)
        )
        table = self._make_table(("Fecha", "Tipo", "Detalle", "Débito", "Crédito", "Saldo"))
        self._fill(
            table,
            [
                (
                    _short(row["date"]), row["movement_type"], row["description"],
                    _money(row["debit"]), _money(row["credit"]), _money(row["balance"]),
                )
                for row in movements.movement_rows
            ],
        )
        self.tabs.addTab(table, f"Cuenta corriente ({len(movements.movement_rows)})")

        returns = ReturnsReportService().report(
            ReturnsFilters(start=self.start, end=self.end, client_id=self.client_id)
        )
        table = self._make_table(("Fecha", "Orden", "Producto", "Devuelta", "Motivo", "Crédito", "Resolución"))
        self._fill(
            table,
            [
                (
                    _short(row["return_date"]), row["order_number"], row["product_name"],
                    row["returned_quantity"], row["reason"],
                    _money(row["credit_amount"]), row["resolution"],
                )
                for row in returns.rows
            ],
        )
        self.tabs.addTab(table, f"Devoluciones ({len(returns.rows)})")

        trace = LotTraceabilityService().report(
            LotTraceabilityFilters(
                client_id=self.client_id, dispatch_from=self.start, dispatch_to=self.end
            )
        )
        table = self._make_table(("Lote", "Elaboración", "Producto", "Orden", "Pallet", "Cantidad"))
        self._fill(
            table,
            [
                (
                    row["lote"], _short(row["elaboration_date"]), row["product_name"],
                    row["order_number"], row["pallet"], row["quantity"],
                )
                for row in trace.rows
            ],
        )
        self.tabs.addTab(table, f"Lotes ({len(trace.rows)})")

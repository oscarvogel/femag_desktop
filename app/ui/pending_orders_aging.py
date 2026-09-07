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
from app.models.masters import Carrier, Client
from app.reports.pending_orders_aging import PendingOrdersAgingService, PendingOrdersFilters


class PendingOrdersAgingDialog(QDialog):
    HEADERS = (
        "Orden",
        "Fecha",
        "Días",
        "Cliente / destino",
        "Estado",
        "Etapa pendiente",
        "Causa",
        "Solicitado",
        "Asignado",
        "Pendiente",
        "Pallets",
        "Trazabilidad",
        "Remito",
        "Transportista",
        "Chofer",
        "Camión",
        "Observaciones",
    )

    def __init__(self, parent=None, *, service: PendingOrdersAgingService | None = None):
        super().__init__(parent)
        self.service = service or PendingOrdersAgingService()
        self.setWindowTitle("Seguimiento de órdenes pendientes")
        self.resize(1600, 850)
        self._build_ui()
        self._load_filters()
        self._set_default_dates()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        title = QLabel("Seguimiento y antigüedad de órdenes pendientes")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(QLabel("Identifica órdenes abiertas, su antigüedad y la causa concreta por la que siguen pendientes."))

        filters = QGridLayout()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.status_combo = QComboBox()
        self.client_combo = QComboBox()
        self.carrier_combo = QComboBox()
        self.stage_combo = QComboBox()
        self.min_age = QSpinBox()
        self.min_age.setRange(0, 3650)
        self.min_age.setSuffix(" días")
        specs = (
            ("Desde", self.date_from),
            ("Hasta", self.date_to),
            ("Estado", self.status_combo),
            ("Cliente", self.client_combo),
            ("Transportista", self.carrier_combo),
            ("Etapa pendiente", self.stage_combo),
            ("Más de / desde", self.min_age),
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
        week = QPushButton("Últimos 7 días")
        week.clicked.connect(self._week)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self.clear_filters)
        open_order = QPushButton("Abrir orden")
        open_order.clicked.connect(self.open_selected_order)
        for button in (consult, today, week, clear, open_order):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.summary_labels = [QLabel() for _ in range(7)]
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
        self.status_combo.addItem("Todos", None)
        for status in LoadOrder.ACTIVE_STATUSES:
            self.status_combo.addItem(status, status)
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        self.carrier_combo.addItem("Todos", None)
        for carrier in Carrier.select().order_by(Carrier.name):
            self.carrier_combo.addItem(carrier.name, carrier.id)
        self.stage_combo.addItem("Todas", None)
        for stage in (
            self.service.STAGE_PREPARATION,
            self.service.STAGE_INCOMPLETE,
            self.service.STAGE_TRACEABILITY,
            self.service.STAGE_DOCUMENTAL,
            self.service.STAGE_READY,
            self.service.STAGE_CLOSURE,
        ):
            self.stage_combo.addItem(stage, stage)

    @staticmethod
    def _to_qdate(value: date) -> QDate:
        return QDate(value.year, value.month, value.day)

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _set_default_dates(self):
        today = date.today()
        self.date_from.setDate(self._to_qdate(today - timedelta(days=30)))
        self.date_to.setDate(self._to_qdate(today))

    def _today(self):
        today = date.today()
        self.date_from.setDate(self._to_qdate(today))
        self.date_to.setDate(self._to_qdate(today))
        self.refresh()

    def _week(self):
        today = date.today()
        self.date_from.setDate(self._to_qdate(today - timedelta(days=6)))
        self.date_to.setDate(self._to_qdate(today))
        self.refresh()

    def clear_filters(self):
        self._set_default_dates()
        self.status_combo.setCurrentIndex(0)
        self.client_combo.setCurrentIndex(0)
        self.carrier_combo.setCurrentIndex(0)
        self.stage_combo.setCurrentIndex(0)
        self.min_age.setValue(0)
        self.refresh()

    def current_filters(self) -> PendingOrdersFilters:
        return PendingOrdersFilters(
            start=self._py_date(self.date_from),
            end=self._py_date(self.date_to),
            status=self.status_combo.currentData(),
            client_id=self.client_combo.currentData(),
            carrier_id=self.carrier_combo.currentData(),
            min_age_days=self.min_age.value(),
            pending_stage=self.stage_combo.currentData(),
        )

    def refresh(self):
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Órdenes pendientes", f"No se pudo generar el seguimiento:\n{exc}")
            return
        totals = result.totals
        values = (
            f"Abiertas: {totals.open_orders}",
            f"> 1 día: {totals.over_1_day}",
            f"> 3 días: {totals.over_3_days}",
            f"> 7 días: {totals.over_7_days}",
            f"Mercadería pendiente: {totals.incomplete_pallets}",
            f"Trazabilidad pendiente: {totals.incomplete_traceability}",
            f"Pendientes de cierre: {totals.pending_closure}",
        )
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        self._render_rows(result.rows)

    def _render_rows(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            values = (
                row["order_number"],
                row["date"].strftime("%d/%m/%Y"),
                row["age_days"],
                row["destinations"] or row["client_name"],
                row["status"],
                row["pending_stage"],
                row["pending_reason"],
                row["requested_quantity"],
                row["assigned_quantity"],
                row["pending_quantity"],
                f'{row["pallets_complete"]}/{row["pallets_expected"]}',
                "Pendiente" if row["traceability_pending"] else "OK",
                "Pendiente" if row["remittance_pending"] else "OK",
                row["carrier_name"],
                row["driver_name"],
                row["truck_domain"],
                row["observations"],
            )
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c in {0, 2, 7, 8, 9}:
                    item.setData(Qt.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 0:
                    item.setData(Qt.UserRole + 1, int(row["order_number"]))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def selected_order_number(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole + 1)
        return int(value) if value is not None else None

    def open_selected_order(self):
        order_number = self.selected_order_number()
        if order_number is None:
            QMessageBox.information(self, "Órdenes pendientes", "Seleccione una orden.")
            return
        parent = self.parent()
        navigate = getattr(parent, "_navigate_to_route", None)
        if navigate is None:
            QMessageBox.warning(self, "Órdenes pendientes", "No se pudo abrir Órdenes de carga.")
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

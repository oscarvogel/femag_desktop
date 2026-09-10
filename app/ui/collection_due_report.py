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
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.masters import Client
from app.reports.collection_due_report import (
    CollectionDueFilters,
    CollectionDueReportService,
)


def _money(value: float) -> str:
    return f"$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class CollectionDueReportDialog(QDialog):
    HEADERS = (
        "Cliente",
        "Orden / presupuesto",
        "Fecha origen",
        "Vencimiento",
        "Importe",
        "Días",
        "Estado",
    )

    def __init__(self, parent=None, *, service: CollectionDueReportService | None = None):
        super().__init__(parent)
        self.service = service or CollectionDueReportService()
        self.setWindowTitle("Vencimientos de cobranzas")
        self.resize(1180, 760)
        self._build_ui()
        self._load_filters()
        self._set_default_dates()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Vencimientos de cobranzas")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(
            QLabel(
                "Importes a cobrar según la fecha de vencimiento registrada en cuenta corriente. "
                "No imputa pagos generales a presupuestos específicos."
            )
        )

        filters = QGridLayout()
        self.client_combo = QComboBox()
        self.status_combo = QComboBox()
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        for widget in (self.date_from, self.date_to):
            widget.setDisplayFormat("dd/MM/yyyy")
        specs = (
            ("Cliente", self.client_combo),
            ("Estado", self.status_combo),
            ("Vence desde", self.date_from),
            ("Vence hasta", self.date_to),
        )
        for col, (label, widget) in enumerate(specs):
            filters.addWidget(QLabel(label), 0, col)
            filters.addWidget(widget, 1, col)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        today_btn = QPushButton("Hoy")
        today_btn.clicked.connect(self._today)
        week_btn = QPushButton("Próximos 7 días")
        week_btn.clicked.connect(self._next_7_days)
        month_btn = QPushButton("Próximos 30 días")
        month_btn.clicked.connect(self._next_30_days)
        clear = QPushButton("Limpiar")
        clear.clicked.connect(self.clear_filters)
        for button in (consult, today_btn, week_btn, month_btn, clear):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.summary_labels = [QLabel() for _ in range(5)]
        for label in self.summary_labels:
            label.setStyleSheet(
                "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
                "border-radius:8px;padding:8px 12px;"
            )
            summary.addWidget(label)
        root.addLayout(summary)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _load_filters(self) -> None:
        self.client_combo.addItem("Todos", None)
        for client in Client.select().where(Client.active == True).order_by(Client.name):  # noqa: E712
            self.client_combo.addItem(client.name, client.id)
        self.status_combo.addItem("Todos", None)
        for status in self.service.STATUSES:
            self.status_combo.addItem(status, status)

    def _set_default_dates(self) -> None:
        today = date.today()
        start = today - timedelta(days=90)
        end = today + timedelta(days=90)
        self.date_from.setDate(QDate(start.year, start.month, start.day))
        self.date_to.setDate(QDate(end.year, end.month, end.day))

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def current_filters(self) -> CollectionDueFilters:
        return CollectionDueFilters(
            client_id=self.client_combo.currentData(),
            due_from=self._py_date(self.date_from),
            due_to=self._py_date(self.date_to),
            status=self.status_combo.currentData(),
        )

    def refresh(self) -> None:
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Vencimientos de cobranzas", f"No se pudo generar el informe:\n{exc}")
            return

        totals = result.totals
        values = (
            f"Vencido: {_money(totals.overdue)}",
            f"Vence hoy: {_money(totals.due_today)}",
            f"Próx. 7 días: {_money(totals.next_7_days)}",
            f"Próx. 30 días: {_money(totals.next_30_days)}",
            f"Total filtrado: {_money(totals.filtered_total)}",
        )
        for label, value in zip(self.summary_labels, values):
            label.setText(value)
        self._render_rows(result.rows)

    def _render_rows(self, rows) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            days_text = (
                f"{abs(row['delta_days'])} vencido(s)"
                if row["delta_days"] < 0
                else ("Hoy" if row["delta_days"] == 0 else f"{row['delta_days']} restante(s)")
            )
            order_text = f"OC-{row['order_number']:06d}" if row["order_number"] is not None else "-"
            values = (
                row["client_name"],
                order_text,
                row["movement_date"].strftime("%d/%m/%Y") if row["movement_date"] else "-",
                row["due_date"].strftime("%d/%m/%Y"),
                _money(row["total_amount"]),
                days_text,
                row["status"],
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 4:
                    item.setData(Qt.UserRole, float(row["total_amount"]))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row_index, col, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)

    def clear_filters(self) -> None:
        self.client_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self._set_default_dates()
        self.refresh()

    def _today(self) -> None:
        today = date.today()
        self._set_range(today, today)
        self.status_combo.setCurrentIndex(self.status_combo.findData("Vence hoy"))
        self.refresh()

    def _next_7_days(self) -> None:
        today = date.today()
        self._set_range(today + timedelta(days=1), today + timedelta(days=7))
        self.status_combo.setCurrentIndex(0)
        self.refresh()

    def _next_30_days(self) -> None:
        today = date.today()
        self._set_range(today + timedelta(days=1), today + timedelta(days=30))
        self.status_combo.setCurrentIndex(0)
        self.refresh()

    def _set_range(self, start: date, end: date) -> None:
        self.date_from.setDate(QDate(start.year, start.month, start.day))
        self.date_to.setDate(QDate(end.year, end.month, end.day))

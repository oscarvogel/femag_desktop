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
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.masters import Client
from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService
from app.reports.managerial_account_risk_html import ManagerialAccountRiskHtmlReport


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


class ManagerialAccountRiskDialog(QDialog):
    HEADERS = (
        "Cliente",
        "Saldo",
        "Vencido",
        "A vencer",
        "7 días",
        "15 días",
        "30 días",
        "Días atraso",
        "Venc. más antiguo",
        "Límite crédito",
        "Disponible",
        "Uso %",
    )

    def __init__(self, parent=None, *, service: ManagerialAccountRiskService | None = None):
        super().__init__(parent)
        self.service = service or ManagerialAccountRiskService()
        self.setWindowTitle("Informe gerencial · Cuenta corriente y deuda vencida")
        self.resize(1420, 760)
        self._row_client_ids: list[int] = []
        self._build_ui()
        self._load_clients()
        self.as_of.setDate(QDate.currentDate())
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel("Cuenta corriente y deuda vencida")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        subtitle = QLabel("Exposición consolidada por cliente, vencimientos y riesgo comercial.")
        subtitle.setStyleSheet("color:#64748b;")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addLayout(heading, 1)
        dashboard = QPushButton("Ver dashboard de cuenta corriente")
        dashboard.clicked.connect(self.open_dashboard)
        header.addWidget(dashboard, 0, Qt.AlignTop)
        root.addLayout(header)

        filters = QGridLayout()
        self.as_of = QDateEdit(calendarPopup=True)
        self.as_of.setDisplayFormat("dd/MM/yyyy")
        self.client_combo = QComboBox()
        self.state_combo = QComboBox()
        self.state_combo.addItem("Todos", "all")
        self.state_combo.addItem("Con deuda", "with_debt")
        self.state_combo.addItem("Sin deuda", "without_debt")
        self.state_combo.addItem("Con deuda vencida", "overdue")
        self.window_combo = QComboBox()
        self.window_combo.addItem("Todos los vencimientos", None)
        self.window_combo.addItem("Vence en 7 días", 7)
        self.window_combo.addItem("Vence en 15 días", 15)
        self.window_combo.addItem("Vence en 30 días", 30)
        filters.addWidget(QLabel("Fecha de corte"), 0, 0)
        filters.addWidget(self.as_of, 1, 0)
        filters.addWidget(QLabel("Cliente"), 0, 1)
        filters.addWidget(self.client_combo, 1, 1)
        filters.addWidget(QLabel("Estado"), 0, 2)
        filters.addWidget(self.state_combo, 1, 2)
        filters.addWidget(QLabel("Vencimiento"), 0, 3)
        filters.addWidget(self.window_combo, 1, 3)
        root.addLayout(filters)

        actions = QHBoxLayout()
        consult = QPushButton("Consultar")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar filtros")
        clear.clicked.connect(self.clear_filters)
        open_ledger = QPushButton("Abrir cuenta corriente del cliente")
        open_ledger.clicked.connect(self.open_selected_client_ledger)
        actions.addWidget(consult)
        actions.addWidget(clear)
        actions.addWidget(open_ledger)
        actions.addStretch(1)
        root.addLayout(actions)

        summary = QHBoxLayout()
        self.balance_label = QLabel()
        self.overdue_label = QLabel()
        self.clients_label = QLabel()
        self.overdue_clients_label = QLabel()
        for label in (self.balance_label, self.overdue_label, self.clients_label, self.overdue_clients_label):
            label.setStyleSheet("font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;")
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
        self.table.doubleClicked.connect(lambda _index: self.open_selected_client_ledger())
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _load_clients(self) -> None:
        self.client_combo.clear()
        self.client_combo.addItem("Todos", None)
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)

    @staticmethod
    def _py_date(widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def current_filters(self) -> AccountRiskFilters:
        return AccountRiskFilters(
            as_of=self._py_date(self.as_of),
            client_id=self.client_combo.currentData(),
            debt_state=str(self.state_combo.currentData()),
            due_window_days=self.window_combo.currentData(),
        )

    def clear_filters(self) -> None:
        self.as_of.setDate(QDate.currentDate())
        self.client_combo.setCurrentIndex(0)
        self.state_combo.setCurrentIndex(0)
        self.window_combo.setCurrentIndex(0)
        self.refresh()

    def refresh(self) -> None:
        try:
            result = self.service.report(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Cuenta corriente", f"No se pudo generar el informe:\n{exc}")
            return
        self._render_result(result)

    def _render_result(self, result) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(result.rows))
        self._row_client_ids = []
        for row_index, row in enumerate(result.rows):
            self._row_client_ids.append(int(row["client_id"]))
            values = (
                row["client_name"], row["balance"], row["overdue"], row["due_future"], row["due_7"], row["due_15"], row["due_30"],
                row["max_days_overdue"], row["oldest_unpaid_due"].strftime("%d/%m/%Y") if row["oldest_unpaid_due"] else "",
                row["credit_limit"], row["available_credit"], row["credit_usage_pct"],
            )
            for column, value in enumerate(values):
                if column in {1,2,3,4,5,6,9,10,11}:
                    if value is None:
                        item = QTableWidgetItem("—")
                    else:
                        number = float(value)
                        suffix = "%" if column == 11 else ""
                        item = NumericTableItem(f"{number:,.2f}{suffix}", number)
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif column == 7:
                    item = NumericTableItem(str(int(value)), int(value))
                else:
                    item = QTableWidgetItem(str(value or ""))
                if column == 0:
                    item.setData(Qt.UserRole, int(row["client_id"]))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        totals = result.totals
        self.balance_label.setText(f"Saldo: $ {totals.balance:,.2f}")
        self.overdue_label.setText(f"Vencido: $ {totals.overdue:,.2f}")
        self.clients_label.setText(f"Clientes con deuda: {totals.clients_with_debt}")
        self.overdue_clients_label.setText(f"Clientes vencidos: {totals.clients_overdue}")

    def selected_client_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.UserRole)) if item and item.data(Qt.UserRole) is not None else None

    def open_selected_client_ledger(self) -> None:
        client_id = self.selected_client_id()
        if client_id is None:
            QMessageBox.information(self, "Cuenta corriente", "Seleccione un cliente en la grilla.")
            return
        client = Client.get_by_id(client_id)
        parent = self.parent()
        callback = getattr(parent, "_open_customer_ledger_for_client", None)
        if callback is None:
            QMessageBox.warning(self, "Cuenta corriente", "No se pudo abrir la cuenta corriente desde esta ventana.")
            return
        self.accept()
        callback(client)

    def open_dashboard(self) -> None:
        try:
            ManagerialAccountRiskHtmlReport(service=self.service).open(self.current_filters())
        except Exception as exc:
            QMessageBox.critical(self, "Dashboard de cuenta corriente", f"No se pudo abrir el dashboard:\n{exc}")

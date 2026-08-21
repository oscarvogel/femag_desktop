from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod


PERIOD_PRESETS = (
    ("Hoy", "hoy"),
    ("Este mes", "este mes"),
    ("Mes anterior", "mes anterior"),
    ("Este año", "este año"),
    ("Personalizado", "personalizado"),
)


def _money(value: float) -> str:
    return f"$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _number(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _variation_text(current: float, previous: float, variation: float | None) -> str:
    if variation is None:
        return "Sin base comparable" if current else "0,0% vs período anterior"
    prefix = "+" if variation > 0 else ""
    return f"{prefix}{_number(variation, 1)}% vs período anterior"


class _KpiCard(QFrame):
    def __init__(self, title: str, object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(108)
        layout = QVBoxLayout(self)
        title_label = QLabel(title)
        title_label.setObjectName("managerialKpiTitle")
        self.value_label = QLabel("-")
        self.value_label.setObjectName("managerialKpiValue")
        self.comparison_label = QLabel("")
        self.comparison_label.setObjectName("managerialKpiComparison")
        self.comparison_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.comparison_label)

    def set_metric(self, value: str, comparison: str = "") -> None:
        self.value_label.setText(value)
        self.comparison_label.setText(comparison)


class ManagerialDashboardPage(QWidget):
    """Read-only executive dashboard backed by ManagerialDashboardService."""

    def __init__(self, *, service: ManagerialDashboardService | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("managerialDashboardPage")
        self.service = service or ManagerialDashboardService()
        self._build_ui()
        self._apply_preset("este mes")
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Dashboard gerencial")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Indicadores ejecutivos de despachos, volumen y exposición de clientes")
        subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        self.period_combo = QComboBox()
        self.period_combo.setObjectName("managerialPeriodPreset")
        for label, key in PERIOD_PRESETS:
            self.period_combo.addItem(label, key)
        self.period_combo.currentIndexChanged.connect(self._period_changed)
        header.addWidget(QLabel("Período"))
        header.addWidget(self.period_combo)

        self.date_from = QDateEdit()
        self.date_from.setObjectName("managerialDateFrom")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to = QDateEdit()
        self.date_to.setObjectName("managerialDateTo")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        header.addWidget(self.date_from)
        header.addWidget(QLabel("a"))
        header.addWidget(self.date_to)

        refresh = QPushButton("Actualizar")
        refresh.setObjectName("managerialRefreshButton")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)

        self.policy_label = QLabel()
        self.policy_label.setObjectName("managerialPolicyLabel")
        self.policy_label.setWordWrap(True)
        root.addWidget(self.policy_label)

        kpis = QGridLayout()
        kpis.setHorizontalSpacing(12)
        kpis.setVerticalSpacing(12)
        self.valued_card = _KpiCard("Despachos valorizados", "managerialKpiValued")
        self.tonnes_card = _KpiCard("Toneladas", "managerialKpiTonnes")
        self.orders_card = _KpiCard("Órdenes / cargas", "managerialKpiOrders")
        self.receivables_card = _KpiCard("Saldo clientes", "managerialKpiReceivables")
        self.overdue_card = _KpiCard("Saldo vencido", "managerialKpiOverdue")
        self.ticket_card = _KpiCard("Ticket promedio", "managerialKpiTicket")
        for index, card in enumerate(
            (
                self.valued_card,
                self.tonnes_card,
                self.orders_card,
                self.receivables_card,
                self.overdue_card,
                self.ticket_card,
            )
        ):
            kpis.addWidget(card, index // 3, index % 3)
        root.addLayout(kpis)

        detail_grid = QGridLayout()
        self.monthly_table = self._table(
            "managerialMonthlyEvolution",
            ("Mes", "Despachos valorizados", "TN", "Órdenes"),
        )
        self.clients_table = self._table(
            "managerialTopClients",
            ("Cliente", "Despachos valorizados", "TN"),
        )
        self.products_table = self._table(
            "managerialTopProducts",
            ("Producto", "Despachos valorizados", "TN"),
        )
        self.status_table = self._table(
            "managerialOrderStatuses",
            ("Estado", "Órdenes"),
        )
        detail_grid.addWidget(self._section("Evolución mensual", self.monthly_table), 0, 0)
        detail_grid.addWidget(self._section("Top clientes", self.clients_table), 0, 1)
        detail_grid.addWidget(self._section("Top productos", self.products_table), 1, 0)
        detail_grid.addWidget(self._section("Estado de órdenes", self.status_table), 1, 1)
        detail_grid.setColumnStretch(0, 1)
        detail_grid.setColumnStretch(1, 1)
        root.addLayout(detail_grid, 1)

    @staticmethod
    def _section(title: str, child: QWidget) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        label = QLabel(title)
        label.setObjectName("managerialSectionTitle")
        layout.addWidget(label)
        layout.addWidget(child, 1)
        return frame

    @staticmethod
    def _table(object_name: str, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setObjectName(object_name)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _period_changed(self) -> None:
        key = self.period_combo.currentData()
        custom = key == "personalizado"
        self.date_from.setEnabled(custom)
        self.date_to.setEnabled(custom)
        if not custom:
            self._apply_preset(key)
            self.refresh()

    def _apply_preset(self, key: str) -> None:
        if key == "personalizado":
            return
        period = ReportPeriod.preset(key)
        self.date_from.setDate(QDate(period.start.year, period.start.month, period.start.day))
        self.date_to.setDate(QDate(period.end.year, period.end.month, period.end.day))
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        index = self.period_combo.findData(key)
        if index >= 0 and self.period_combo.currentIndex() != index:
            self.period_combo.blockSignals(True)
            self.period_combo.setCurrentIndex(index)
            self.period_combo.blockSignals(False)

    def selected_period(self) -> ReportPeriod:
        start_qdate = self.date_from.date()
        end_qdate = self.date_to.date()
        return ReportPeriod(
            date(start_qdate.year(), start_qdate.month(), start_qdate.day()),
            date(end_qdate.year(), end_qdate.month(), end_qdate.day()),
            self.period_combo.currentText(),
        )

    def refresh(self) -> None:
        snapshot = self.service.snapshot(self.selected_period())
        self.policy_label.setText(
            "Criterio V1: se consideran despachos efectivos las órdenes en estado "
            + ", ".join(snapshot.effective_statuses)
            + ". Las devoluciones se muestran en su circuito operativo y no se descuentan todavía del KPI valorizado."
        )
        self.valued_card.set_metric(
            _money(snapshot.valued_dispatches.current),
            _variation_text(
                snapshot.valued_dispatches.current,
                snapshot.valued_dispatches.previous,
                snapshot.valued_dispatches.variation_percent,
            ),
        )
        self.tonnes_card.set_metric(
            f"{_number(snapshot.tonnes.current, 3)} TN",
            _variation_text(snapshot.tonnes.current, snapshot.tonnes.previous, snapshot.tonnes.variation_percent),
        )
        self.orders_card.set_metric(
            str(int(snapshot.orders.current)),
            _variation_text(snapshot.orders.current, snapshot.orders.previous, snapshot.orders.variation_percent),
        )
        self.receivables_card.set_metric(_money(snapshot.total_receivables), "Saldo consolidado actual")
        self.overdue_card.set_metric(_money(snapshot.overdue_receivables), f"Vencido al {snapshot.period.end:%d/%m/%Y}")
        self.ticket_card.set_metric(
            _money(snapshot.average_ticket.current),
            _variation_text(
                snapshot.average_ticket.current,
                snapshot.average_ticket.previous,
                snapshot.average_ticket.variation_percent,
            ),
        )

        self._fill_table(
            self.monthly_table,
            [
                (row["label"], _money(row["total"]), _number(row["tonnes"], 3), str(row["orders"]))
                for row in snapshot.monthly_evolution
            ],
        )
        self._fill_table(
            self.clients_table,
            [(row["name"], _money(row["total"]), _number(row["tonnes"], 3)) for row in snapshot.top_clients],
        )
        self._fill_table(
            self.products_table,
            [(row["name"], _money(row["total"]), _number(row["tonnes"], 3)) for row in snapshot.top_products],
        )
        self._fill_table(
            self.status_table,
            [(row["status"], str(row["count"])) for row in snapshot.order_statuses],
        )

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row_index, column_index, item)
        table.resizeColumnsToContents()

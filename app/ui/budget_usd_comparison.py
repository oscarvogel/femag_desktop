"""Dialogo de comparacion de presupuestos ARS/USD (#973)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from app.reports.budget_usd_comparison import (
    RATE_SIDE_AVERAGE,
    RATE_SIDE_BUY,
    RATE_SIDE_SELL,
    RATE_TYPES,
    SIDE_LABELS,
    SOURCE_LABELS,
    TYPE_LABELS,
    BudgetUsdComparisonService,
    BudgetUsdFilters,
    monthly_evolution,
    type_comparison,
)
from app.reports.budget_usd_comparison_export import export_budget_usd_comparison_xlsx
from app.reports.budget_usd_comparison_html import export_budget_usd_comparison_html


def _money(value) -> str:
    if value is None:
        return "-"
    return f"$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _number(value, decimals: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _usd(value) -> str:
    if value is None:
        return "-"
    return f"USD {_number(value, 2)}"


def _percent(value) -> str:
    if value is None:
        return "-"
    prefix = "+" if float(value) > 0 else ""
    return f"{prefix}{_number(value, 1)}%"


def _status_label(value: str) -> str:
    return "Anulado" if value == "annulled" else "Activo"


def _origin_label(value: str) -> str:
    return "Orden de carga" if value == "load_order" else "Manual"


class BudgetUsdComparisonDialog(QDialog):
    """Vista de solo lectura, con exportacion Excel."""

    def __init__(
        self,
        *,
        service: BudgetUsdComparisonService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service or BudgetUsdComparisonService()
        self.setWindowTitle("Comparacion de presupuestos ARS/USD")
        self.resize(1180, 760)
        self._build_ui()
        self._load_default_range()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel("Comparacion historica de presupuestos ARS/USD")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Convierte cada presupuesto con la cotizacion de su fecha. "
            "Si falta, puede usar la anterior y lo marca. No modifica presupuestos."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(6)
        self.type_combo = QComboBox()
        self.type_combo.setObjectName("budgetUsdTypeCombo")
        for rate_type in RATE_TYPES:
            self.type_combo.addItem(TYPE_LABELS.get(rate_type, rate_type), rate_type)
        self.type_combo.setCurrentIndex(
            max(0, self.type_combo.findData("blue"))
        )
        self.type_combo.currentIndexChanged.connect(self.refresh)

        self.source_combo = QComboBox()
        self.source_combo.setObjectName("budgetUsdSourceCombo")
        for value, label in (
            ("argentinadatos", SOURCE_LABELS["argentinadatos"]),
            ("dolarapi", SOURCE_LABELS["dolarapi"]),
            ("bna", SOURCE_LABELS["bna"]),
            ("any", SOURCE_LABELS["any"]),
        ):
            self.source_combo.addItem(label, value)
        self.source_combo.currentIndexChanged.connect(self.refresh)

        self.side_combo = QComboBox()
        self.side_combo.setObjectName("budgetUsdSideCombo")
        for value in (RATE_SIDE_SELL, RATE_SIDE_BUY, RATE_SIDE_AVERAGE):
            self.side_combo.addItem(SIDE_LABELS[value], value)
        self.side_combo.currentIndexChanged.connect(self.refresh)

        self.date_from = QDateEdit()
        self.date_from.setObjectName("budgetUsdFrom")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_to = QDateEdit()
        self.date_to.setObjectName("budgetUsdTo")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")

        self.include_annulled = QCheckBox("Incluir anulados")
        self.include_annulled.setObjectName("budgetUsdIncludeAnnulled")
        self.include_annulled.stateChanged.connect(self.refresh)
        self.allow_prior = QCheckBox("Permitir cotizacion anterior")
        self.allow_prior.setObjectName("budgetUsdAllowPrior")
        self.allow_prior.setChecked(True)
        self.allow_prior.stateChanged.connect(self.refresh)

        filters.addWidget(QLabel("Tipo"), 0, 0)
        filters.addWidget(self.type_combo, 0, 1)
        filters.addWidget(QLabel("Fuente"), 0, 2)
        filters.addWidget(self.source_combo, 0, 3)
        filters.addWidget(QLabel("Punta"), 0, 4)
        filters.addWidget(self.side_combo, 0, 5)
        filters.addWidget(QLabel("Desde"), 1, 0)
        filters.addWidget(self.date_from, 1, 1)
        filters.addWidget(QLabel("Hasta"), 1, 2)
        filters.addWidget(self.date_to, 1, 3)
        filters.addWidget(self.include_annulled, 1, 4)
        filters.addWidget(self.allow_prior, 1, 5)
        root.addLayout(filters)

        summary = QGridLayout()
        summary.setHorizontalSpacing(18)
        summary.setVerticalSpacing(4)
        self.total_ars_label = QLabel("-")
        self.total_usd_label = QLabel("-")
        self.rate_label = QLabel("-")
        self.coverage_label = QLabel("-")
        for label, widget, column in (
            ("Presupuestos ARS", self.total_ars_label, 0),
            ("Total USD", self.total_usd_label, 1),
            ("Cotizacion ponderada", self.rate_label, 2),
            ("Cobertura", self.coverage_label, 3),
        ):
            caption = QLabel(label)
            caption.setObjectName("managerialKpiTitle")
            summary.addWidget(caption, 0, column)
            widget.setObjectName("budgetUsdSummaryValue")
            summary.addWidget(widget, 1, column)
        root.addLayout(summary)

        self.evolution_table = QTableWidget(0, 7)
        self.evolution_table.setObjectName("budgetUsdEvolutionTable")
        self.evolution_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.evolution_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.evolution_table.setAlternatingRowColors(True)
        self.evolution_table.verticalHeader().setVisible(False)
        self.evolution_table.setHorizontalHeaderLabels(
            (
                "Mes",
                "Presupuestos",
                "Total ARS",
                "Total USD",
                "Var ARS",
                "Var USD",
                "Cobertura",
            )
        )
        self.evolution_table.horizontalHeader().setStretchLastSection(True)

        self.comparison_table = QTableWidget(0, 8)
        self.comparison_table.setObjectName("budgetUsdComparisonTable")
        self.comparison_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.comparison_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.comparison_table.setAlternatingRowColors(True)
        self.comparison_table.verticalHeader().setVisible(False)
        self.comparison_table.setHorizontalHeaderLabels(
            (
                "Tipo",
                "Presupuestos",
                "Total ARS",
                "Total USD",
                "Cotizacion ponderada",
                "Cobertura",
                "Dif. USD vs blue",
                "Dif. % vs blue",
            )
        )
        self.comparison_table.horizontalHeader().setStretchLastSection(True)

        self.table = QTableWidget(0, 13)
        self.table.setObjectName("budgetUsdTable")
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalHeaderLabels(
            (
                "Fecha",
                "Presupuesto",
                "Cliente",
                "Estado",
                "Origen",
                "Total ARS",
                "Cotizacion",
                "Fecha efectiva",
                "Fuente",
                "Fallback",
                "Cobertura",
                "Total USD",
                "Observacion",
            )
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        tabs = QTabWidget()
        tabs.setObjectName("budgetUsdTabs")
        tabs.addTab(self.evolution_table, "Evolucion mensual ARS/USD")
        tabs.addTab(self.comparison_table, "Comparativo por tipo")
        tabs.addTab(self.table, "Detalle por presupuesto")
        root.addWidget(tabs, 1)

        actions = QHBoxLayout()
        refresh = QPushButton("Actualizar")
        refresh.setObjectName("budgetUsdRefreshButton")
        refresh.clicked.connect(self.refresh)
        export = QPushButton("Exportar Excel (todos los tipos)")
        export.setObjectName("budgetUsdExportButton")
        export.clicked.connect(self._export)
        export_html = QPushButton("Exportar HTML con graficos")
        export_html.setObjectName("budgetUsdExportHtmlButton")
        export_html.clicked.connect(self._export_html)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        actions.addWidget(refresh)
        actions.addWidget(export)
        actions.addWidget(export_html)
        actions.addStretch(1)
        actions.addWidget(close)
        root.addLayout(actions)

    def _load_default_range(self) -> None:
        first, last = self.service.budget_date_range()
        if first is None or last is None:
            last = date.today()
            first = last - timedelta(days=30)
        self.date_from.setDate(QDate(first.year, first.month, first.day))
        self.date_to.setDate(QDate(last.year, last.month, last.day))

    def _filters(self) -> BudgetUsdFilters:
        start = self.date_from.date()
        end = self.date_to.date()
        return BudgetUsdFilters(
            start_date=date(start.year(), start.month(), start.day()),
            end_date=date(end.year(), end.month(), end.day()),
            rate_type=str(self.type_combo.currentData()),
            source=str(self.source_combo.currentData()),
            side=str(self.side_combo.currentData()),
            include_annulled=self.include_annulled.isChecked(),
            allow_prior=self.allow_prior.isChecked(),
        )

    def refresh(self) -> None:
        filters = self._filters()
        try:
            results = self.service.compare_all(filters)
            result = next(
                (item for item in results if item.rate_type == filters.rate_type),
                results[0],
            )
        except Exception as exc:  # noqa: BLE001 - error amable en UI
            QMessageBox.warning(self, "Comparacion USD", f"No se pudo calcular:\n{exc}")
            return
        summary = result.summary
        self.total_ars_label.setText(_money(summary.total_ars))
        self.total_usd_label.setText(_usd(summary.total_usd))
        self.rate_label.setText(
            f"{_number(summary.weighted_rate, 6)} ARS/USD"
            if summary.weighted_rate is not None
            else "-"
        )
        self.coverage_label.setText(
            f"{_number(summary.coverage_percent, 1)}% "
            f"({summary.covered_budgets}/{summary.total_budgets})"
        )
        self._fill_evolution(result)
        self._fill_comparison(results)
        self.table.setRowCount(len(result.rows))
        for index, row in enumerate(result.rows):
            values = (
                row.issue_date.strftime("%d/%m/%Y"),
                f"PRES-{row.budget_number:06d}",
                row.client_name,
                _status_label(row.status),
                _origin_label(row.origin),
                _money(row.total_ars),
                _number(row.rate, 6),
                row.rate_effective_date.strftime("%d/%m/%Y")
                if row.rate_effective_date
                else "-",
                row.rate_source or "-",
                "Si" if row.used_fallback else "No",
                {
                    "exact": "Exacta",
                    "prior": "Anterior",
                    "missing": "Sin cotizacion",
                }.get(row.coverage, row.coverage),
                _usd(row.total_usd),
                row.warning,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in {5, 11}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if row.coverage == "missing" and column in {10, 11, 12}:
                    item.setForeground(Qt.red)
                self.table.setItem(index, column, item)
        self.table.resizeColumnsToContents()

    def _fill_evolution(self, result) -> None:
        months = monthly_evolution(result.rows)
        self.evolution_table.setRowCount(len(months))
        for index, month in enumerate(months):
            values = (
                month.label,
                str(month.budgets),
                _money(month.total_ars),
                _usd(month.total_usd),
                _percent(month.variation_ars),
                _percent(month.variation_usd),
                f"{_number(month.coverage_percent, 1)}%",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.evolution_table.setItem(index, column, item)
        self.evolution_table.resizeColumnsToContents()

    def _fill_comparison(self, results) -> None:
        rows = type_comparison(results, base_type="blue")
        self.comparison_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            no_data = row.covered_budgets == 0
            values = (
                TYPE_LABELS.get(row.rate_type, row.rate_type),
                str(row.budgets),
                _money(row.total_ars),
                "-" if no_data else _usd(row.total_usd),
                "-" if no_data else _number(row.weighted_rate, 6),
                f"{_number(row.coverage_percent, 1)}%",
                "-"
                if no_data or row.difference_usd is None
                else _usd(row.difference_usd),
                "-" if no_data else _percent(row.difference_percent),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.comparison_table.setItem(index, column, item)
        self.comparison_table.resizeColumnsToContents()

    def _export_html(self) -> None:
        filters = self._filters()
        default_name = (
            f"comparacion_presupuestos_usd_"
            f"{filters.start_date:%Y%m%d}_{filters.end_date:%Y%m%d}.html"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar comparacion USD a HTML",
            default_name,
            "HTML (*.html)",
        )
        if not path:
            return
        try:
            results = self.service.compare_all(filters)
            out = export_budget_usd_comparison_html(results, Path(path))
        except Exception as exc:  # noqa: BLE001 - error amable en UI
            QMessageBox.warning(self, "Exportar comparacion USD", f"No se pudo exportar:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Exportar comparacion USD",
            f"Exportado:\n{out}\n\nIncluye graficos de evolucion mensual y comparativo por tipo.",
        )

    def _export(self) -> None:
        filters = self._filters()
        default_name = (
            f"comparacion_presupuestos_usd_"
            f"{filters.start_date:%Y%m%d}_{filters.end_date:%Y%m%d}.xlsx"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar comparacion USD",
            default_name,
            "Excel (*.xlsx)",
        )
        if not path:
            return
        try:
            results = self.service.compare_all(filters)
            out = export_budget_usd_comparison_xlsx(results, Path(path))
        except Exception as exc:  # noqa: BLE001 - error amable en UI
            QMessageBox.warning(self, "Exportar comparacion USD", f"No se pudo exportar:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Exportar comparacion USD",
            f"Exportado:\n{out}\n\nSe incluyeron {len(results)} tipos.",
        )

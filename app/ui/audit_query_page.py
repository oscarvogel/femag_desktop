from __future__ import annotations

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.audit_query_service import AuditQueryService
from app.utils.datetime_utils import utc_datetime_to_local


class AuditQueryPage(QWidget):
    PAGE_SIZE = 50

    def __init__(self, *, parent=None, service: AuditQueryService | None = None):
        super().__init__(parent)
        self.setObjectName("auditQueryPage")
        self.service = service or AuditQueryService()
        self.current_page = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Auditoría")
        title.setObjectName("auditQueryTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Consulta de eventos históricos por documento, fecha, usuario, módulo y acción."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("auditQueryFilters")
        grid = QGridLayout(filters)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        self.module_combo = QComboBox()
        self.module_combo.setObjectName("auditQueryModule")
        self.user_combo = QComboBox()
        self.user_combo.setObjectName("auditQueryUser")
        self.action_combo = QComboBox()
        self.action_combo.setObjectName("auditQueryAction")
        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("auditQueryReference")
        self.reference_input.setPlaceholderText("Ej.: OC-000154, REC-00000010, PRES-000022...")

        options = self.service.filter_options()
        self._fill_combo(self.module_combo, "Todos los módulos", options["modules"])
        self._fill_combo(self.user_combo, "Todos los usuarios", options["users"])
        self._fill_combo(self.action_combo, "Todas las acciones", options["actions"])

        self.date_from_enabled = QCheckBox("Desde")
        self.date_from_enabled.setObjectName("auditQueryDateFromEnabled")
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setObjectName("auditQueryDateFrom")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setEnabled(False)
        self.date_from_enabled.toggled.connect(self.date_from.setEnabled)

        self.date_to_enabled = QCheckBox("Hasta")
        self.date_to_enabled.setObjectName("auditQueryDateToEnabled")
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setObjectName("auditQueryDateTo")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setEnabled(False)
        self.date_to_enabled.toggled.connect(self.date_to.setEnabled)

        self.search_button = QPushButton("Aplicar filtros")
        self.search_button.setObjectName("auditQuerySearchButton")
        self.clear_button = QPushButton("Limpiar")
        self.clear_button.setObjectName("auditQueryClearButton")

        grid.addWidget(QLabel("Módulo"), 0, 0)
        grid.addWidget(QLabel("Usuario"), 0, 1)
        grid.addWidget(QLabel("Acción"), 0, 2)
        grid.addWidget(QLabel("Documento / referencia"), 0, 3)
        grid.addWidget(self.module_combo, 1, 0)
        grid.addWidget(self.user_combo, 1, 1)
        grid.addWidget(self.action_combo, 1, 2)
        grid.addWidget(self.reference_input, 1, 3)
        grid.addWidget(self.date_from_enabled, 2, 0)
        grid.addWidget(self.date_from, 2, 1)
        grid.addWidget(self.date_to_enabled, 2, 2)
        grid.addWidget(self.date_to, 2, 3)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.search_button)
        grid.addLayout(actions, 3, 0, 1, 4)
        layout.addWidget(filters)

        results_bar = QHBoxLayout()
        self.results_label = QLabel("")
        self.results_label.setObjectName("auditQueryResultsLabel")
        self.previous_button = QPushButton("Anterior")
        self.previous_button.setObjectName("auditQueryPreviousButton")
        self.next_button = QPushButton("Siguiente")
        self.next_button.setObjectName("auditQueryNextButton")
        results_bar.addWidget(self.results_label)
        results_bar.addStretch(1)
        results_bar.addWidget(self.previous_button)
        results_bar.addWidget(self.next_button)
        layout.addLayout(results_bar)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("auditQueryTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Fecha y hora",
                "Módulo",
                "Documento",
                "Usuario",
                "Acción",
                "Evolución",
                "Motivo / resumen",
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)

        header = self.table.horizontalHeader()
        for column in range(6):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 180)
        layout.addWidget(self.table, 1)

        self.search_button.clicked.connect(self.apply_filters)
        self.clear_button.clicked.connect(self.clear_filters)
        self.reference_input.returnPressed.connect(self.apply_filters)
        self.previous_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.refresh()

    @staticmethod
    def _fill_combo(combo: QComboBox, first: str, values: list[str]) -> None:
        combo.addItem(first, None)
        for value in values:
            combo.addItem(value, value)

    def apply_filters(self) -> None:
        self.current_page = 0
        self.refresh()

    def clear_filters(self) -> None:
        self.module_combo.setCurrentIndex(0)
        self.user_combo.setCurrentIndex(0)
        self.action_combo.setCurrentIndex(0)
        self.reference_input.clear()
        self.date_from_enabled.setChecked(False)
        self.date_to_enabled.setChecked(False)
        self.current_page = 0
        self.refresh()

    def previous_page(self) -> None:
        if self.current_page <= 0:
            return
        self.current_page -= 1
        self.refresh()

    def next_page(self) -> None:
        if not self.next_button.isEnabled():
            return
        self.current_page += 1
        self.refresh()

    def refresh(self) -> None:
        page = self.service.search_page(
            module=self.module_combo.currentData(),
            user=self.user_combo.currentData(),
            action=self.action_combo.currentData(),
            reference=self.reference_input.text().strip() or None,
            date_from=(
                self.date_from.date().toPyDate()
                if self.date_from_enabled.isChecked()
                else None
            ),
            date_to=(
                self.date_to.date().toPyDate()
                if self.date_to_enabled.isChecked()
                else None
            ),
            page=self.current_page,
            page_size=self.PAGE_SIZE,
        )

        # Evita repaints parciales mientras se insertan las celdas.
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(page.rows))
            for row_index, row in enumerate(page.rows):
                occurred = utc_datetime_to_local(row.occurred_at)
                values = (
                    occurred.strftime("%d/%m/%Y %H:%M"),
                    row.module,
                    self.service.display_reference(row),
                    row.user or "Sistema",
                    row.action.replace("_", " "),
                    self.service.transition(row),
                    self.service.reason_or_summary(row),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    if column == 0:
                        item.setTextAlignment(Qt.AlignCenter)
                    item.setToolTip(str(value or ""))
                    self.table.setItem(row_index, column, item)
        finally:
            self.table.setUpdatesEnabled(True)

        self.previous_button.setEnabled(page.has_previous)
        self.next_button.setEnabled(page.has_next)
        self.results_label.setText(
            f"Página {page.page + 1} · Mostrando {len(page.rows)} "
            f"evento{'s' if len(page.rows) != 1 else ''} de auditoría."
        )

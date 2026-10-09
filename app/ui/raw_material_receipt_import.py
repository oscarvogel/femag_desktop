from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QDateEdit, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.raw_material_receipt_import_service import (
    RawMaterialReceiptImportService, ReceiptTotals,
)
from app.ui.form_feedback import FormFeedback


STATUS_LABELS = {
    RawMaterialReceiptImportService.NEW: "Nuevo",
    RawMaterialReceiptImportService.UNCHANGED: "Sin cambios",
    RawMaterialReceiptImportService.MODIFIED: "Modificado",
}


def _kg(value: Decimal) -> str:
    return f"{value:,.2f}"


class RawMaterialReceiptImportPage(QWidget):
    """Consulta tickets de materia prima en femagfab e importa los faltantes.

    La pantalla nunca escribe en femagfab. La fécula teórica se calcula siempre
    como TOTALK * PROMEDIO / 100; el valor FECULA del legacy se muestra
    sólo como referencia histórica.
    """

    HEADERS = (
        "Ticket",
        "Proveedor",
        "Producto",
        "Kg liquidables",
        "Rinde promedio",
        "Fécula teórica",
        "Fécula legacy",
        "Estado",
    )

    def __init__(self, parent=None, *, service: RawMaterialReceiptImportService | None = None):
        super().__init__(parent)
        self.service = service or RawMaterialReceiptImportService()
        self.previews = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        heading = QLabel("Recepciones de materia prima")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Consulta los tickets finalizados de femagfab por fecha. "
            "La importación guarda un snapshot propio y no modifica el sistema de balanza."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Fecha"))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("rawMaterialReceiptDayInput")
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        controls.addWidget(self.day)
        consult = QPushButton("Consultar")
        consult.setObjectName("rawMaterialReceiptConsultButton")
        consult.setProperty("uiRole", "primary")
        consult.clicked.connect(self.refresh)
        controls.addWidget(consult)
        self.import_button = QPushButton("Importar nuevos")
        self.import_button.setObjectName("rawMaterialReceiptImportButton")
        self.import_button.setProperty("uiRole", "secondary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_new)
        controls.addWidget(self.import_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary_label = QLabel("Seleccione una fecha y consulte los tickets.")
        self.summary_label.setObjectName("rawMaterialReceiptSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
            "border-radius:8px;padding:8px 12px;"
        )
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("rawMaterialReceiptTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.feedback = FormFeedback("rawMaterialReceiptFeedback")
        self.feedback.show_info("Seleccione una fecha y consulte los tickets.")
        layout.addWidget(self.feedback)

    def selected_date(self) -> date:
        qd = self.day.date()
        return date(qd.year(), qd.month(), qd.day())

    def _clear_result(self, message: str) -> None:
        """Deja la pantalla sin filas previas que puedan importarse por error."""
        self.previews = []
        self.table.setRowCount(0)
        self.import_button.setEnabled(False)
        self.summary_label.setText(message)

    def _render_totals(self, totals: ReceiptTotals, pending: int) -> None:
        self.summary_label.setText(
            f"{totals.tickets} ticket(s) · {_kg(totals.payable_kg)} kg liquidables · "
            f"rinde ponderado {totals.weighted_yield:,.2f} % · "
            f"{_kg(totals.theoretical_starch_kg)} kg de fécula teórica · "
            f"{pending} ticket(s) sin importar"
        )

    def refresh(self) -> None:
        try:
            previews, totals = self.service.preview(self.selected_date())
        except Exception as exc:
            self._clear_result("No se pudo consultar femagfab.")
            self.feedback.show_error(f"No se pudo consultar femagfab: {exc}")
            return

        self.previews = previews
        self.table.setRowCount(len(previews))
        for index, preview in enumerate(previews):
            row = preview.row
            values = [
                row.comp,
                row.supplier_name or row.supplier_code,
                row.product_name or row.product_code,
                _kg(row.payable_kg),
                f"{row.yield_average:,.2f} %",
                _kg(row.theoretical_starch_kg),
                _kg(row.legacy_starch_kg),
                STATUS_LABELS.get(preview.status, preview.status),
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

        pending = sum(1 for preview in previews if preview.status == self.service.NEW)
        self._render_totals(totals, pending)
        self.import_button.setEnabled(pending > 0)
        if pending:
            self.feedback.show_info(
                f"{pending} ticket(s) nuevos para {self.selected_date():%d/%m/%Y}."
            )
        else:
            self.feedback.show_success(
                f"Sin tickets nuevos para {self.selected_date():%d/%m/%Y}."
            )

    def import_new(self) -> None:
        try:
            created = self.service.import_new(self.previews)
        except Exception as exc:
            self.feedback.show_error(f"No se pudo importar: {exc}")
            return
        self.feedback.show_success(f"Se importaron {created} ticket(s) nuevos.")
        self.refresh()

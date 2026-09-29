from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QDateEdit, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.raw_material_receipt_import_service import RawMaterialReceiptImportService


class RawMaterialReceiptImportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.service = RawMaterialReceiptImportService()
        self.previews = []
        layout = QVBoxLayout(self)
        title = QLabel("Importar recepciones de materia prima")
        title.setObjectName("heading")
        layout.addWidget(title)
        layout.addWidget(QLabel("Lee tickets finalizados de femagfab sin modificar el sistema de balanza."))

        controls = QHBoxLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        preview = QPushButton("Consultar")
        self.import_button = QPushButton("Importar nuevos")
        self.import_button.setEnabled(False)
        preview.clicked.connect(self.refresh)
        self.import_button.clicked.connect(self.import_new)
        controls.addWidget(QLabel("Fecha"))
        controls.addWidget(self.day)
        controls.addWidget(preview)
        controls.addWidget(self.import_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary = QLabel("Seleccione una fecha y consulte los tickets.")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Ticket", "Proveedor", "Producto", "Kg liquidables", "Rinde", "Fécula teórica", "Fécula legacy", "Estado"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)

    def selected_date(self) -> date:
        qd = self.day.date()
        return date(qd.year(), qd.month(), qd.day())

    def refresh(self):
        try:
            self.previews, totals = self.service.preview(self.selected_date())
        except Exception as exc:
            QMessageBox.critical(self, "Importar recepciones", f"No se pudo consultar femagfab:\n{exc}")
            return
        self.table.setRowCount(len(self.previews))
        for index, preview in enumerate(self.previews):
            row = preview.row
            values = [
                row.comp, row.supplier_name or row.supplier_code, row.product_name or row.product_code,
                f"{row.payable_kg:,.2f}", f"{row.yield_average:,.2f} %",
                f"{row.theoretical_starch_kg:,.2f}", f"{row.legacy_starch_kg:,.2f}", preview.status,
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self.summary.setText(
            f"{totals.tickets} tickets · {totals.payable_kg:,.2f} kg liquidables · "
            f"rinde ponderado {totals.weighted_yield:,.2f} % · "
            f"{totals.theoretical_starch_kg:,.2f} kg teóricos"
        )
        self.import_button.setEnabled(any(p.status == self.service.NEW for p in self.previews))

    def import_new(self):
        try:
            created = self.service.import_new(self.previews)
        except Exception as exc:
            QMessageBox.critical(self, "Importar recepciones", f"No se pudo importar:\n{exc}")
            return
        QMessageBox.information(self, "Importar recepciones", f"Se importaron {created} tickets nuevos.")
        self.refresh()

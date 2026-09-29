from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.production_part_service import ProductionPartService
from app.ui.form_feedback import FormFeedback


class ProductionPartPage(QWidget):
    HEADERS = ("Fecha", "Turno", "Kg mandioca procesados", "Kg fécula producidos", "Rinde real", "Observación")

    def __init__(self, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or ProductionPartService()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel("Partes de producción")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel("Registrá lo efectivamente procesado y producido por turno. No se asignan camiones ni tickets individuales.")
        subheading.setObjectName("subheading")
        layout.addWidget(subheading)

        form = QFormLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.shift = QComboBox()
        self.shift.setEditable(True)
        self.shift.addItems(["Mañana", "Tarde", "Noche"])
        self.processed = QDoubleSpinBox()
        self.processed.setRange(0, 999999999)
        self.processed.setDecimals(2)
        self.processed.setSuffix(" kg")
        self.produced = QDoubleSpinBox()
        self.produced.setRange(0, 999999999)
        self.produced.setDecimals(2)
        self.produced.setSuffix(" kg")
        self.observations = QLineEdit()
        form.addRow("Fecha", self.day)
        form.addRow("Turno", self.shift)
        form.addRow("Kg mandioca procesados", self.processed)
        form.addRow("Kg fécula producidos", self.produced)
        form.addRow("Observación", self.observations)
        layout.addLayout(form)

        actions = QHBoxLayout()
        save = QPushButton("Guardar parte")
        save.setObjectName("productionPartSaveButton")
        save.clicked.connect(self.save)
        actions.addWidget(save)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.feedback = FormFeedback("productionPartFeedback")
        layout.addWidget(self.feedback)

    def selected_date(self):
        value = self.day.date()
        return value.toPyDate()

    def refresh(self):
        rows = self.service.for_day(self.selected_date())
        totals = self.service.totals(rows)
        self.summary.setText(
            f"{totals.parts} parte(s) · {totals.cassava_processed_kg:,.2f} kg procesados · "
            f"{totals.starch_produced_kg:,.2f} kg producidos · rinde real {totals.real_yield:,.2f} %"
        )
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                row.production_date.strftime("%d/%m/%Y"), row.shift,
                f"{row.cassava_processed_kg:,.2f}", f"{row.starch_produced_kg:,.2f}",
                f"{row.real_yield:,.2f} %", row.observations or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def save(self):
        try:
            row = self.service.create(
                production_date=self.selected_date(), shift=self.shift.currentText(),
                cassava_processed_kg=self.processed.value(), starch_produced_kg=self.produced.value(),
                observations=self.observations.text(),
            )
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        self.feedback.show_success(f"Parte guardado. Rinde real: {row.real_yield:,.2f} %.")
        self.processed.setValue(0)
        self.produced.setValue(0)
        self.observations.clear()
        self.refresh()

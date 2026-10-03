from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QDateEdit, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.production_contrast_service import ProductionContrastService
from app.ui.form_feedback import FormFeedback

RECEIPT_HEADERS = ("Proveedor", "Mandioca", "Kg liquidados", "Rinde prom.", "Fecula teorica")
PART_HEADERS = ("Turno", "Estado", "Producto", "Bolsas", "Kg embolsados")


class ProductionContrastPage(QWidget):
    """Fecula teorica contra fecula real, dia por dia.

    Responde la pregunta que la planta se hace todos los dias: entramos X kilos
    de mandioca, el legacy estima que rendiran Y kilos de fecula, y cuanto se
    embolsÃ³ de verdad.

    El rinde real se calcula sobre la mandioca **recibida**, porque el sistema
    no registra cuantos kilos entraron al proceso. Si queda producto del dia
    anterior (arranque o WIP) el numero sale corrido y hay que tomarlo con
    pinzas; por eso la pantalla lo dice en vez de disimularlo.
    """

    def __init__(self, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or ProductionContrastService()
        self.feedback = FormFeedback("productionContrastFeedback")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Contraste de produccion")
        title.setProperty("class", "pageTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            "Compara la fecula que la planta recibio segun el legacy contra la que "
            "realmente embolsÃ³. Solo lectura: no modifica nada."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        form = QFormLayout()
        self.day = QDateEdit()
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.setDate(QDate.currentDate())
        self.day.dateChanged.connect(self.refresh)
        form.addRow("Fecha", self.day)
        layout.addLayout(form)

        layout.addWidget(self.feedback)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setProperty("class", "card")
        layout.addWidget(self.summary)

        self.assumption_note = QLabel()
        self.assumption_note.setWordWrap(True)
        self.assumption_note.setProperty("class", "muted")
        layout.addWidget(self.assumption_note)

        receipts_title = QLabel("Tickets importados de femagfab")
        receipts_title.setProperty("class", "sectionTitle")
        layout.addWidget(receipts_title)
        self.receipts_table = self._build_table(RECEIPT_HEADERS)
        layout.addWidget(self.receipts_table)

        parts_title = QLabel("Partes de embolsado")
        parts_title.setProperty("class", "sectionTitle")
        layout.addWidget(parts_title)
        self.parts_table = self._build_table(PART_HEADERS)
        layout.addWidget(self.parts_table)

        layout.addStretch(1)
        self.refresh()

    @staticmethod
    def _build_table(headers) -> QTableWidget:
        tabla = QTableWidget(0, len(headers))
        tabla.setHorizontalHeaderLabels(list(headers))
        tabla.verticalHeader().setVisible(False)
        tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        tabla.setSelectionMode(QTableWidget.NoSelection)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return tabla

    def selected_date(self) -> date:
        return self.day.date().toPyDate()

    def refresh(self) -> None:
        dia = self.selected_date()
        try:
            self._fill(dia)
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo calcular el contraste: {exc}")

    def _fill(self, dia: date) -> None:
        from app.services.production_contrast_service import ProductionContrastService as Svc

        contraste = Svc.for_day(dia)

        if not contraste.has_receipts and not contraste.has_confirmed_production:
            self.summary.setText(
                f"{dia:%d/%m/%Y} Â· sin tickets importados y sin partes confirmados."
            )
        else:
            lineas = [
                f"{dia:%d/%m/%Y}",
                f"Mandioca recibida: {contraste.received_kg:,.0f} kg "
                f"({contraste.received_tickets} ticket(s))",
                f"Rinde teorico: {contraste.theoretical_yield_pct:.2f} %",
                f"Fecula teorica: {contraste.theoretical_starch_kg:,.2f} kg",
                f"Fecula real embolsada: {contraste.real_starch_kg:,.2f} kg "
                f"({contraste.real_bags:,} bolsa(s) en {contraste.real_parts} parte(s))",
            ]
            rinde_real = contraste.real_yield_pct
            if rinde_real is None:
                lineas.append("Rinde real: no hay mandioca recibida para compararlo.")
            else:
                lineas.append(f"Rinde real: {rinde_real:.2f} %")
                desvio = contraste.deviation_kg
                desvio_pct = contraste.deviation_pct
                if desvio is not None and desvio_pct is not None:
                    signo = "por encima" if desvio >= 0 else "por debajo"
                    lineas.append(
                        f"Desvio: {desvio:+,.2f} kg ({desvio_pct:+.2f} %) "
                        f"{signo} de la teoria"
                    )
            self.summary.setText(" Â· ".join(lineas))

        self.assumption_note.setText(self._warning(contraste))
        self._fill_receipts(dia)
        self._fill_parts(dia)

    @staticmethod
    def _warning(contraste) -> str:
        avisos = []
        if contraste.has_receipts:
            avisos.append(
                "El rinde real se calcula sobre la mandioca recibida, porque el sistema "
                "no registra cuantos kilos entraron al proceso. Si queda producto del dia "
                "anterior, el numero sale corrido."
            )
        if contraste.pending_parts:
            avisos.append(
                f"{contraste.pending_parts} parte(s) en borrador no cuentan como produccion "
                "real: se pueden seguir modificando."
            )
        if not contraste.has_receipts:
            avisos.append("No hay tickets importados de femagfab para esta fecha.")
        if not contraste.has_confirmed_production and contraste.has_receipts:
            avisos.append("No hay partes confirmados: no se puede calcular el rinde real.")
        return " ".join(avisos)

    def _fill_receipts(self, dia: date) -> None:
        from app.services.production_contrast_service import ProductionContrastService as Svc

        filas = Svc.receipt_lines(dia)
        self.receipts_table.setRowCount(len(filas))
        for indice, (proveedor, producto, kg, rinde, fecula) in enumerate(filas):
            valores = (
                proveedor, producto, f"{kg:,.0f}", f"{rinde:.2f} %", f"{fecula:,.2f}",
            )
            for columna, valor in enumerate(valores):
                self.receipts_table.setItem(indice, columna, QTableWidgetItem(str(valor)))

    def _fill_parts(self, dia: date) -> None:
        from app.services.production_contrast_service import ProductionContrastService as Svc

        filas = Svc.part_lines(dia)
        self.parts_table.setRowCount(len(filas))
        for indice, (turno, estado, producto, bolsas, kg) in enumerate(filas):
            valores = (turno, estado, producto, f"{bolsas:,}", f"{kg:,.2f}")
            for columna, valor in enumerate(valores):
                self.parts_table.setItem(indice, columna, QTableWidgetItem(str(valor)))

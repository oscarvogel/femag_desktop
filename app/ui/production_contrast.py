from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.production_contrast_service import ProductionContrastService
from app.ui.form_feedback import FormFeedback

RECEIPT_HEADERS = ("Proveedor", "Mandioca", "Kg liquidados", "Rinde prom.", "Fecula teorica")
PART_HEADERS = ("Fecha", "Turno", "Estado", "Producto", "Bolsas", "Kg embolsados")

PERIODO_DIA = "Dia"
PERIODO_MES = "Mes"

# Los nombres de objeto salen del tema de la app (#kpiCard, #kpiValue, ...):
# si se inventan otros, la pagina queda pelada como un formulario de Qt.
TARJETAS = (
    "mandioca",
    "teorica",
    "real",
    "rinde",
    "desvio",
)


def _metric_card(titulo: str):
    frame = QFrame()
    frame.setObjectName("kpiCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 13, 14, 14)
    layout.setSpacing(4)
    titulo_label = QLabel(titulo)
    titulo_label.setObjectName("kpiLabel")
    titulo_label.setWordWrap(True)
    valor_label = QLabel("-")
    valor_label.setObjectName("kpiValue")
    valor_label.setWordWrap(True)
    ayuda_label = QLabel("")
    ayuda_label.setObjectName("kpiHelper")
    ayuda_label.setWordWrap(True)
    layout.addWidget(titulo_label)
    layout.addWidget(valor_label)
    layout.addWidget(ayuda_label)
    return frame, valor_label, ayuda_label


class ProductionContrastPage(QWidget):
    """Fecula teorica contra fecula real, por dia o por mes.

    El mes es el periodo util. Como no hay forma de saber cuantos kilos de
    mandioca entraron al proceso, el rinde diario no significa nada: si el
    material de un dia se procesa al otro, el numerador y el denominador son de
    dias distintos. Sumando el mes entero el desfase se promedia y queda una
    media que si se puede usar. El dia queda para ver el detalle.
    """

    def __init__(self, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or ProductionContrastService()
        self.feedback = FormFeedback("productionContrastFeedback")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Contraste de producción")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Compara la fécula que la planta recibió según el legacy contra la que "
            "realmente embolsó. El mes es la media útil: como no se sabe en qué día "
            "se procesó la mandioca, el agregado mensual promedia el desfase."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        etiqueta_periodo = QLabel("Periodo")
        self.period = QComboBox()
        self.period.setObjectName("productionContrastPeriod")
        self.period.setFixedWidth(110)
        self.period.addItems([PERIODO_MES, PERIODO_DIA])
        self.period.currentTextChanged.connect(self.refresh)
        etiqueta_fecha = QLabel("Fecha")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("productionContrastDay")
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.setFixedWidth(150)
        self.day.dateChanged.connect(self.refresh)
        filtros.addWidget(etiqueta_periodo)
        filtros.addWidget(self.period)
        filtros.addSpacing(18)
        filtros.addWidget(etiqueta_fecha)
        filtros.addWidget(self.day)
        filtros.addStretch(1)
        layout.addLayout(filtros)

        layout.addWidget(self.feedback)

        tarjetas = QHBoxLayout()
        tarjetas.setSpacing(12)
        self.kpis = {}
        for clave, titulo in (
            ("mandioca", "Mandioca recibida"),
            ("teorica", "Fécula teórica"),
            ("real", "Fécula real embolsada"),
            ("rinde", "Rinde real"),
            ("desvio", "Desvío vs teoría"),
        ):
            frame, valor, ayuda = _metric_card(titulo)
            tarjetas.addWidget(frame, 1)
            self.kpis[clave] = (valor, ayuda)
        layout.addLayout(tarjetas)

        self.nota = QLabel()
        self.nota.setObjectName("subheading")
        self.nota.setWordWrap(True)
        layout.addWidget(self.nota)

        tickets_heading = QLabel("Tickets importados de femagfab")
        tickets_heading.setObjectName("subheading")
        layout.addWidget(tickets_heading)
        self.receipts_table = self._build_table(
            RECEIPT_HEADERS, "productionContrastReceiptsTable"
        )
        layout.addWidget(self.receipts_table, 1)

        partes_heading = QLabel("Partes de embolsado")
        partes_heading.setObjectName("subheading")
        layout.addWidget(partes_heading)
        self.parts_table = self._build_table(PART_HEADERS, "productionContrastPartsTable")
        layout.addWidget(self.parts_table, 1)

        self.refresh()

    @staticmethod
    def _build_table(headers, object_name: str) -> QTableWidget:
        tabla = QTableWidget(0, len(headers))
        tabla.setObjectName(object_name)
        tabla.setHorizontalHeaderLabels(list(headers))
        tabla.verticalHeader().setVisible(False)
        tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        tabla.setSelectionMode(QAbstractItemView.NoSelection)
        tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return tabla

    def selected_date(self) -> date:
        return self.day.date().toPyDate()

    def refresh(self) -> None:
        try:
            self._fill()
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo calcular el contraste: {exc}")

    def _fill(self) -> None:
        dia = self.selected_date()
        if self.period.currentText() == PERIODO_MES:
            inicio, fin = ProductionContrastService.month_bounds(dia)
        else:
            inicio, fin = dia, dia

        contraste = ProductionContrastService.between(inicio, fin)
        self._fill_cards(contraste)
        self.nota.setText(self._note(contraste))
        self._fill_receipts(inicio, fin)
        self._fill_parts(inicio, fin)

    def _fill_cards(self, contraste) -> None:
        valor, _ = self.kpis["mandioca"]
        valor.setText(f"{contraste.received_kg:,.0f} kg")
        self.kpis["mandioca"][1].setText(
            f"{contraste.received_tickets} ticket(s) - {contraste.label}"
        )

        valor, _ = self.kpis["teorica"]
        valor.setText(f"{contraste.theoretical_starch_kg:,.2f} kg")
        self.kpis["teorica"][1].setText(
            f"rinde teórico ponderado {contraste.theoretical_yield_pct:.2f} %"
        )

        valor, _ = self.kpis["real"]
        valor.setText(f"{contraste.real_starch_kg:,.2f} kg")
        self.kpis["real"][1].setText(
            f"{contraste.real_bags:,} bolsa(s) en {contraste.real_parts} parte(s) "
            f"confirmado(s)"
        )

        valor, ayuda = self.kpis["rinde"]
        rinde_real = contraste.real_yield_pct
        if rinde_real is None:
            valor.setText("-")
            ayuda.setText("sin mandioca recibida para comparar")
        else:
            valor.setText(f"{rinde_real:.2f} %")
            ayuda.setText("media del mes" if contraste.is_month else "solo ese día")

        valor, ayuda = self.kpis["desvio"]
        desvio = contraste.deviation_kg
        desvio_pct = contraste.deviation_pct
        if desvio is None or desvio_pct is None:
            valor.setText("-")
            ayuda.setText("sin teoría con la cual comparar")
        else:
            valor.setText(f"{desvio:+,.2f} kg")
            ayuda.setText(
                f"{desvio_pct:+.2f} % - "
                + ("por encima" if desvio >= 0 else "por debajo")
            )

    @staticmethod
    def _note(contraste) -> str:
        avisos = []
        if contraste.is_month:
            avisos.append(
                "No se sabe cuántos kilos de mandioca entraron al proceso, así que el "
                "rinde se calcula sobre la recibida. Al sumar todo el mes el desfase se "
                "promedia: por eso el mes es la media que sirve."
            )
        elif contraste.has_receipts:
            avisos.append(
                "El detalle diario no sirve para juzgar el rinde: si el material de un día "
                "se procesa al otro, el numerador y el denominador son de días distintos. "
                "Mire el mes para la media."
            )
        if contraste.pending_parts:
            avisos.append(
                f"{contraste.pending_parts} parte(s) en borrador no cuentan como producción "
                "real: se pueden seguir modificando."
            )
        if not contraste.has_receipts:
            avisos.append("No hay tickets importados de femagfab para este periodo.")
        if not contraste.has_confirmed_production and contraste.has_receipts:
            avisos.append("No hay partes confirmados: no se puede calcular el rinde real.")
        return " ".join(avisos)

    def _fill_receipts(self, inicio: date, fin: date) -> None:
        filas = ProductionContrastService.receipt_lines(inicio, fin)
        self.receipts_table.setRowCount(len(filas))
        for indice, (proveedor, producto, kg, rinde, fecula) in enumerate(filas):
            valores = (
                proveedor, producto, f"{kg:,.0f}", f"{rinde:.2f} %", f"{fecula:,.2f}",
            )
            for columna, valor in enumerate(valores):
                self.receipts_table.setItem(indice, columna, QTableWidgetItem(str(valor)))

    def _fill_parts(self, inicio: date, fin: date) -> None:
        filas = ProductionContrastService.part_lines(inicio, fin)
        self.parts_table.setRowCount(len(filas))
        for indice, (fecha, turno, estado, producto, bolsas, kg) in enumerate(filas):
            valores = (
                f"{fecha:%d/%m/%Y}", turno, estado, producto, f"{bolsas:,}", f"{kg:,.2f}",
            )
            for columna, valor in enumerate(valores):
                self.parts_table.setItem(indice, columna, QTableWidgetItem(str(valor)))

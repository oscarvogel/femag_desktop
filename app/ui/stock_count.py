from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QDateEdit, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.models.stock_count import StockCount
from app.services.stock_count_service import StockCountError, StockCountService
from app.services.stock_service import StockService
from app.ui.form_feedback import FormFeedback

HEADERS = ("Producto", "Stock del libro (kg)", "Bolsas contadas", "Equivale a (kg)", "Diferencia (kg)")


def _kg(valor: Decimal) -> str:
    return f"{valor:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


class StockCountPage(QWidget):
    """Conteo fisico del deposito (#574).

    El operador cuenta **bolsas**, que es lo que hay en el deposito, y los kilos
    se derivan del peso del producto: la misma cuenta que en los partes de
    produccion.

    Dos cosas que la pantalla tiene que dejar claras:

    - **El stock del libro es la foto del momento en que se agrego la linea.** Si
      despues se emite una orden, el ajuste no tiene que absorberla: la
      diferencia es de la orden, no del conteo.
    - **Un conteo parcial solo ajusta lo contado.** Lo que no se conto queda como
      esta; no se ajusta a cero.
    """

    def __init__(self, parent=None, *, service=None, current_username: str | None = None):
        super().__init__(parent)
        self.service = service or StockCountService(current_user=current_username or "")
        self.current_username = current_username
        self.feedback = FormFeedback("stockCountFeedback")
        self.inputs: dict[int, QSpinBox] = {}
        self.lineas: dict[int, object] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Conteo físico")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Contá cuántas bolsas hay de cada producto. Los kilos salen del peso de la "
            "bolsa y la diferencia contra el libro se ajusta al cerrar el conteo, sin "
            "reescribir los movimientos anteriores."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        etiqueta = QLabel("Fecha del conteo")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("stockCountDay")
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.dateChanged.connect(self.refresh)
        filtros.addWidget(etiqueta)
        filtros.addWidget(self.day)
        filtros.addStretch(1)
        layout.addLayout(filtros)

        layout.addWidget(self.feedback)

        self.status = QLabel()
        self.status.setObjectName("subheading")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setObjectName("stockCountTable")
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.motivo = QLineEdit()
        self.motivo.setObjectName("stockCountReason")
        self.motivo.setPlaceholderText("Motivo de la diferencia (opcional, queda asentado)")
        layout.addWidget(self.motivo)

        acciones = QHBoxLayout()
        self.save_button = QPushButton("Guardar conteo")
        self.save_button.setObjectName("stockCountSaveButton")
        self.save_button.clicked.connect(self.save_count)
        self.close_button = QPushButton("Cerrar conteo y ajustar")
        self.close_button.setObjectName("stockCountCloseButton")
        self.close_button.clicked.connect(self.close_count)
        acciones.addWidget(self.save_button)
        acciones.addWidget(self.close_button)
        acciones.addStretch(1)
        layout.addLayout(acciones)

        self.refresh()

    def selected_date(self) -> date:
        return self.day.date().toPyDate()

    def refresh(self) -> None:
        dia = self.selected_date()
        try:
            conteo = StockCount.get_or_none(
                (StockCount.count_date == dia) & (StockCount.status == StockCount.STATUS_OPEN)
            )
            productos = self.service.countable_products()
            lineas = {linea.product_id: linea for linea in (conteo.lines if conteo else [])}
            self._fill(dia, conteo, productos, lineas)
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo abrir el conteo: {exc}")

    def _fill(self, dia, conteo, productos, lineas) -> None:
        cerrado = conteo is not None and not conteo.is_open
        total_lineas = len(lineas)
        diferencias = [
            linea for linea in lineas.values() if linea.has_difference
        ]
        kg_diferencia = sum((linea.difference_kg for linea in diferencias), Decimal("0.000"))

        if conteo is not None and conteo.is_open:
            self.status.setText(
                f"Conteo abierto del {dia:%d/%m/%Y} por "
                f"{conteo.counted_by or 'sin usuario'} · {total_lineas} producto(s) "
                f"cargado(s) · {len(diferencias)} con diferencia "
                f"({_kg(kg_diferencia)} kg netos)"
            )
        elif conteo is not None:
            self.status.setText(
                f"El conteo del {dia:%d/%m/%Y} está cerrado. Los ajustes ya están "
                "en el libro; para contar de nuevo usá otra fecha."
            )
        else:
            self.status.setText(
                f"{dia:%d/%m/%Y} · cargá las bolsas de los productos que contaste. "
                "Lo que dejes en 0 no genera movimiento, y lo que no cargues no se ajusta."
            )

        self.table.setRowCount(len(productos))
        self.inputs = {}
        self.lineas = {}
        sin_peso: list[str] = []
        for indice, producto in enumerate(productos):
            linea = lineas.get(producto.id)
            saldo = StockService.balance_for(producto).balance_kg
            contable = self.service.is_countable_in_bags(producto)
            self.table.setItem(indice, 0, QTableWidgetItem(producto.name))
            self.table.setItem(
                indice, 1, QTableWidgetItem(_kg(linea.calculated_kg if linea else saldo))
            )
            if not contable and linea is None:
                # Sin peso de bolsa no hay conversion: N bolsas serian 0 kg y al
                # cerrar el conteo el ajuste llevaria el saldo del libro a cero
                # (#650). No se ofrece el campo, y se dice por que, en vez de
                # dejar que el operador cargue un numero que no significa nada.
                sin_peso.append(producto.name)
                celda = QTableWidgetItem("falta peso de bolsa")
                celda.setToolTip(
                    f"{producto.name} no tiene peso de bolsa cargado. Cargalo en "
                    "Productos para poder contar este producto en bolsas."
                )
                celda.setForeground(Qt.gray)
                self.table.setItem(indice, 2, celda)
                for columna in (3, 4):
                    vacia = QTableWidgetItem("-")
                    vacia.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    vacia.setForeground(Qt.gray)
                    self.table.setItem(indice, columna, vacia)
                continue
            entrada = QSpinBox()
            entrada.setObjectName("stockCountBags")
            entrada.setRange(0, 9_999_999)
            entrada.setSingleStep(1)
            entrada.setSuffix(" bolsas")
            entrada.setValue(int(linea.counted_units) if linea else 0)
            entrada.setReadOnly(linea is not None or cerrado)
            self.table.setCellWidget(indice, 2, entrada)
            self.inputs[producto.id] = entrada
            if linea is not None:
                self.lineas[producto.id] = linea
            self.table.setItem(
                indice, 3, QTableWidgetItem(_kg(linea.counted_kg) if linea else "-")
            )
            diferencia = linea.difference_kg if linea else Decimal("0.000")
            celda = QTableWidgetItem(
                _kg(diferencia) if linea else "-"
            )
            celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(indice, 4, celda)

        if sin_peso:
            aviso = (
                f" · {len(sin_peso)} producto(s) sin peso de bolsa cargado, no "
                f"contables: {', '.join(sin_peso[:5])}"
                f"{'…' if len(sin_peso) > 5 else ''}"
            )
            self.status.setText(self.status.text() + aviso)

        editable = not cerrado
        self.save_button.setEnabled(editable)
        self.close_button.setEnabled(editable and total_lineas > 0)
        self.motivo.setEnabled(editable)

    def save_count(self) -> None:
        dia = self.selected_date()
        try:
            conteo = self.service.open_count(dia)
            motivo = self.motivo.text().strip() or None
            for producto_id, entrada in self.inputs.items():
                bolsas = entrada.value()
                existente = self.lineas.get(producto_id)
                if bolsas == 0 and (existente is None or not existente.has_difference):
                    if existente is not None:
                        self.service.remove_line(conteo, existente)
                    continue
                self.service.add_line(conteo, self._producto(producto_id), bolsas, reason=motivo)
        except StockCountError as exc:
            self.feedback.show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo guardar el conteo: {exc}")
            return
        self.refresh()
        self.feedback.show_success("Conteo guardado.")

    @staticmethod
    def _producto(producto_id: int):
        from app.models.masters import Product

        return Product.get_or_none(Product.id == producto_id)

    def close_count(self) -> None:
        dia = self.selected_date()
        try:
            conteo = StockCount.get_or_none(
                (StockCount.count_date == dia) & (StockCount.status == StockCount.STATUS_OPEN)
            )
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo leer el conteo: {exc}")
            return
        if conteo is None:
            self.feedback.show_warning("Primero guardá el conteo.")
            return

        diferencias = self.service.differences(conteo)
        lineas = list(conteo.lines)
        if not diferencias:
            answer = QMessageBox.question(
                self, "Cerrar conteo",
                "Ninguna línea difiere del libro. ¿Cerrar igual?\n\n"
                "Queda asentado que el conteo cuadró, y no se genera ningún ajuste.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        else:
            detalle = "\n".join(
                f"  · {linea.product.name}: {_kg(linea.calculated_kg)} kg en el libro, "
                f"{_kg(linea.counted_units)} bolsas contadas = {_kg(linea.counted_kg)} kg "
                f"({_kg(linea.difference_kg)} kg)"
                for linea in diferencias[:10]
            )
            extra = "" if len(diferencias) <= 10 else f"\n  ... y {len(diferencias) - 10} más"
            answer = QMessageBox.question(
                self, "Cerrar conteo y ajustar",
                f"{len(diferencias)} de {len(lineas)} productos difieren del libro:\n"
                f"{detalle}{extra}\n\n"
                "¿Cerrar el conteo y generar los ajustes en el libro?\n"
                "Queda asentado con usuario y fecha, y no se reescribe nada.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            movimientos = self.service.close_count(conteo)
        except StockCountError as exc:
            self.feedback.show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo cerrar el conteo: {exc}")
            return

        self.refresh()
        kg = sum((m.quantity_kg for m in movimientos), Decimal("0.000"))
        if movimientos:
            self.feedback.show_success(
                f"Conteo cerrado: {len(movimientos)} ajuste(s) por {_kg(kg)} kg."
            )
        else:
            self.feedback.show_success("Conteo cerrado: el depósito cuadraba con el libro.")

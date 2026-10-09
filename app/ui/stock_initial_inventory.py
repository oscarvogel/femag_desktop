from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QDateEdit, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.services.stock_inventory_service import (
    StockInventoryError,
    StockInventoryService,
)
from app.services.stock_service import (
    ZERO,
    StockService,
    bag_weight_of,
    is_countable_in_bags,
)
from app.ui.form_feedback import FormFeedback

HEADERS = ("Producto", "Bolsas contadas", "Equivale a (kg)", "Stock en el libro (kg)")


def _kg(valor: Decimal) -> str:
    return f"{valor:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")



class StockInitialInventoryPage(QWidget):
    """Carga del inventario inicial: el punto de partida del libro de stock.

    Es una operacion de una vez: se cuenta el deposito en una fecha de corte y se
    carga. Ahi el saldo deja de ser cero y empieza a decir la verdad. Despues
    solo se mueve con produccion, despachos y ajustes.

    **Se cuenta en bolsas, igual que Conteo fisico y partes de produccion.** Los
    kilos se derivan del peso de bolsa del producto y se muestran al lado, para
    que el operador vea la conversion antes de confirmar. Antes esta pantalla
    pedia kilos escritos a mano, y el mismo numero significaba una cosa u otra
    segun donde se escribiera: 500 en Conteo fisico eran 500 bolsas, aca eran
    500 kg. Ver #651.

    Si el conteo se equivoco se anula y se vuelve a cargar; cargar dos veces la
    misma fecha no reemplaza nada y la pantalla lo avisa en vez de dejar pasar un
    cambio silencioso.
    """

    def __init__(self, parent=None, *, service=None, current_username: str | None = None):
        super().__init__(parent)
        self.service = service or StockInventoryService()
        self.current_username = current_username
        self.feedback = FormFeedback("stockInitialInventoryFeedback")
        self.inputs: dict[int, QSpinBox] = {}
        self.pesos: dict[int, Decimal] = {}
        self.nombres: dict[int, str] = {}
        self.filas: dict[int, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Inventario inicial")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Contá el depósito en una fecha de corte y cargalo acá. Contá las "
            "bolsas, como en Conteo físico: los kilos salen del peso de bolsa del "
            "producto. Es el punto de partida del libro: a partir de esta carga el "
            "saldo se deriva solo de la producción, los despachos y los ajustes. "
            "Las órdenes ya cerradas no se cargan."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        etiqueta = QLabel("Fecha del conteo")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("stockInitialInventoryDay")
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

        self.entradas = QTableWidget(0, len(HEADERS))
        self.entradas.setObjectName("stockInitialInventoryTable")
        self.entradas.setHorizontalHeaderLabels(list(HEADERS))
        self.entradas.verticalHeader().setVisible(False)
        self.entradas.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.entradas.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.entradas, 1)

        self.observations = QLineEdit()
        self.observations.setObjectName("stockInitialInventoryObservations")
        self.observations.setPlaceholderText("Observación del conteo (opcional)")
        layout.addWidget(self.observations)

        acciones = QHBoxLayout()
        self.load_button = QPushButton("Cargar inventario inicial")
        self.load_button.setObjectName("stockInitialInventoryLoadButton")
        self.load_button.clicked.connect(self.load_inventory)
        self.void_button = QPushButton("Anular conteo de esta fecha")
        self.void_button.setObjectName("stockInitialInventoryVoidButton")
        self.void_button.clicked.connect(self.void_inventory)
        acciones.addWidget(self.load_button)
        acciones.addWidget(self.void_button)
        acciones.addStretch(1)
        layout.addLayout(acciones)

        self.refresh()

    def selected_date(self) -> date:
        return self.day.date().toPyDate()

    def refresh(self) -> None:
        dia = self.selected_date()
        try:
            ya_cargado = self.service.has_initial(dia)
            anulado = self.service.is_voided(dia)
            conteos = self.service.initial_counts_in_bags(dia)
            productos = self.service.countable_products()
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo leer el estado del conteo: {exc}")
            return

        sin_peso = [
            producto.name for producto in productos
            if not is_countable_in_bags(producto)
        ]
        aviso_sin_peso = ""
        if sin_peso:
            aviso_sin_peso = (
                f" · {len(sin_peso)} producto(s) sin peso de bolsa cargado, no "
                f"contables: {', '.join(sin_peso[:5])}"
                f"{'…' if len(sin_peso) > 5 else ''}"
            )

        if ya_cargado and not anulado:
            self.status.setText(
                f"El {dia:%d/%m/%Y} ya tiene inventario inicial cargado. "
                "Si el conteo estaba mal, anulalo y volvé a cargarlo: cargar dos "
                "veces la misma fecha no reemplaza nada." + aviso_sin_peso
            )
        elif anulado:
            self.status.setText(
                f"El inventario inicial del {dia:%d/%m/%Y} está anulado. "
                "Cargá el conteo en otra fecha." + aviso_sin_peso
            )
        else:
            self.status.setText(
                f"{dia:%d/%m/%Y} · cargá las bolsas de cada producto. "
                "Lo que dejes en 0 no genera movimiento. La columna de kilos es la "
                "equivalencia según el peso de bolsa del producto, y la última "
                "columna es lo que el libro tiene hoy: no se edita desde acá."
                + aviso_sin_peso
            )

        self._fill_table(productos, conteos, bloqueado=ya_cargado)
        self.load_button.setEnabled(not ya_cargado and bool(productos))
        self.void_button.setEnabled(ya_cargado and not anulado)
        self.observations.setEnabled(not ya_cargado)

    def _fill_table(self, productos, conteos: dict, *, bloqueado: bool) -> None:
        self.entradas.setRowCount(len(productos))
        self.inputs = {}
        self.pesos = {}
        self.nombres = {}
        self.filas = {}
        for indice, producto in enumerate(productos):
            self.entradas.setItem(indice, 0, QTableWidgetItem(producto.name))
            if not is_countable_in_bags(producto):
                # Sin peso de bolsa no hay conversion, y arrancar el libro en
                # cero porque el dato de maestro falta no es una carga: es un
                # error. Se muestra bloqueado y con el motivo (#650, #651).
                celda = QTableWidgetItem("falta peso de bolsa")
                celda.setToolTip(
                    f"{producto.name} no tiene peso de bolsa cargado. Cargalo en "
                    "Productos para poder contar este producto en bolsas."
                )
                celda.setForeground(Qt.gray)
                self.entradas.setItem(indice, 1, celda)
                for columna in (2, 3):
                    vacia = QTableWidgetItem("-")
                    vacia.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    vacia.setForeground(Qt.gray)
                    self.entradas.setItem(indice, columna, vacia)
                continue
            entrada = QSpinBox()
            entrada.setObjectName("stockInitialInventoryBags")
            entrada.setRange(0, 9_999_999)
            entrada.setSingleStep(1)
            entrada.setSuffix(" bolsas")
            entrada.setValue(int(conteos[producto.id]) if producto.id in conteos else 0)
            entrada.setReadOnly(bloqueado)
            entrada.valueChanged.connect(self._actualizar_equivalencia)
            self.entradas.setCellWidget(indice, 1, entrada)
            self.inputs[producto.id] = entrada
            self.pesos[producto.id] = bag_weight_of(producto)
            self.nombres[producto.id] = producto.name
            self.filas[producto.id] = indice
            # Lo que dice el libro hoy. Sin esta columna el operador carga el
            # conteo y no tiene forma de verificar que haya quedado bien.
            saldo = StockService.balance_for(producto).balance_kg
            item = QTableWidgetItem(_kg(saldo))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.entradas.setItem(indice, 3, item)
        self._actualizar_equivalencia()

    def _kilos_de(self, producto_id: int) -> Decimal:
        """Kilos que representan las bolsas escritas para un producto."""
        entrada = self.inputs.get(producto_id)
        if entrada is None:
            return ZERO
        return (Decimal(entrada.value()) * self.pesos[producto_id]).quantize(
            Decimal("0.001")
        )

    def _actualizar_equivalencia(self) -> None:
        """Refleja los kilos de cada fila mientras el operador escribe.

        El campo es de bolsas, pero el libro es en kilos. Mostrar la
        equivalencia en vivo es lo que evita el error de escribir 500 pensando
        en kilos y que se carguen 500 bolsas.
        """
        for producto_id, indice in self.filas.items():
            entrada = self.inputs[producto_id]
            kilos = self._kilos_de(producto_id)
            celda = self.entradas.item(indice, 2)
            if celda is None:
                celda = QTableWidgetItem()
                self.entradas.setItem(indice, 2, celda)
            celda.setText(_kg(kilos) if entrada.value() else "-")
            celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def load_inventory(self) -> None:
        dia = self.selected_date()
        conteos: dict[int, int] = {}
        for producto_id, entrada in self.inputs.items():
            bolsas = entrada.value()
            if bolsas > 0:
                conteos[producto_id] = bolsas
        if not conteos:
            self.feedback.show_error("Cargá al menos un producto con bolsas.")
            return
        total_bolsas = sum(conteos.values())
        total_kg = sum((self._kilos_de(pid) for pid in conteos), ZERO)
        detalle = "\n".join(
            f"  · {self.nombres[pid]}: {conteos[pid]} bolsa(s) de "
            f"{_kg(self.pesos[pid])} kg = {_kg(self._kilos_de(pid))} kg"
            for pid in sorted(conteos)
        )
        answer = QMessageBox.question(
            self, "Cargar inventario inicial",
            f"¿Cargar el inventario inicial del {dia:%d/%m/%Y}?\n\n"
            f"{len(conteos)} producto(s) · {total_bolsas} bolsa(s) = "
            f"{_kg(total_kg)} kg\n{detalle}\n\n"
            "Es el punto de partida del libro de stock. Si el conteo se repite, "
            "anulá el anterior: cargar dos veces la misma fecha no reemplaza nada.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            movimientos = self.service.load_initial(
                dia, conteos,
                current_user=self.current_username,
                observations=self.observations.text(),
            )
        except StockInventoryError as exc:
            self.feedback.show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo cargar el inventario: {exc}")
            return
        self.refresh()
        self.feedback.show_success(
            f"Inventario inicial cargado: {len(movimientos)} producto(s), "
            f"{total_bolsas} bolsa(s) = {_kg(total_kg)} kg."
        )

    def void_inventory(self) -> None:
        dia = self.selected_date()
        motivo, acepto = QInputDialog.getText(
            self, "Anular inventario inicial",
            f"El conteo del {dia:%d/%m/%Y} va a quedar en el libro junto con su "
            "movimiento contrario, con tu nombre y el motivo.\n\nMotivo:",
        )
        if not acepto:
            return
        if not (motivo or "").strip():
            self.feedback.show_warning("El motivo es obligatorio.")
            return
        try:
            reversas = self.service.reverse_initial(
                dia, current_user=self.current_username, reason=motivo
            )
        except StockInventoryError as exc:
            self.feedback.show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo anular el inventario: {exc}")
            return
        self.refresh()
        self.feedback.show_success(
            f"Inventario anulado: {len(reversas)} movimiento(s) contrario(s) generados."
        )

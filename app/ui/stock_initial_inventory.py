from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView, QDateEdit, QDoubleSpinBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.stock_inventory_service import (
    StockInventoryError,
    StockInventoryService,
)
from app.services.stock_service import StockService
from app.ui.form_feedback import FormFeedback

HEADERS = ("Producto", "Unidad", "Stock contado (kg)", "Stock en el libro (kg)")


class StockInitialInventoryPage(QWidget):
    """Carga del inventario inicial: el punto de partida del libro de stock.

    Es una operacion de una vez: se cuenta el deposito en una fecha de corte y se
    carga. Ahi el saldo deja de ser cero y empieza a decir la verdad. Despues
    solo se mueve con produccion, despachos y ajustes.

    Si el conteo se equivoco se anula y se vuelve a cargar; cargar dos veces la
    misma fecha no reemplaza nada y la pantalla lo avisa en vez de dejar pasar un
    cambio silencioso.
    """

    def __init__(self, parent=None, *, service=None, current_username: str | None = None):
        super().__init__(parent)
        self.service = service or StockInventoryService()
        self.current_username = current_username
        self.feedback = FormFeedback("stockInitialInventoryFeedback")
        self.inputs: dict[int, QDoubleSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Inventario inicial")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Contá el depósito en una fecha de corte y cargalo acá. Es el punto de "
            "partida del libro: a partir de esta carga el saldo se deriva solo de la "
            "producción, los despachos y los ajustes. Las órdenes ya cerradas no se "
            "cargan."
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

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setObjectName("stockInitialInventoryTable")
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

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
            cantidades = self.service.initial_quantities(dia)
            productos = self.service.countable_products()
        except Exception as exc:  # noqa: BLE001
            self.feedback.show_error(f"No se pudo leer el estado del conteo: {exc}")
            return

        if ya_cargado and not anulado:
            self.status.setText(
                f"El {dia:%d/%m/%Y} ya tiene inventario inicial cargado. "
                "Si el conteo estaba mal, anulalo y volvé a cargarlo: cargar dos "
                "veces la misma fecha no reemplaza nada."
            )
        elif anulado:
            self.status.setText(
                f"El inventario inicial del {dia:%d/%m/%Y} está anulado. "
                "Cargá el conteo en otra fecha."
            )
        else:
            self.status.setText(
                f"{dia:%d/%m/%Y} · cargá los kilos de cada producto. "
                "Lo que dejes en 0 no genera movimiento. La última columna es lo "
                "que el libro tiene hoy, y no se edita desde acá."
            )

        self._fill_table(productos, cantidades, bloqueado=ya_cargado)
        self.load_button.setEnabled(not ya_cargado and bool(productos))
        self.void_button.setEnabled(ya_cargado and not anulado)
        self.observations.setEnabled(not ya_cargado)

    def _fill_table(self, productos, cantidades: dict, *, bloqueado: bool) -> None:
        self.table.setRowCount(len(productos))
        self.inputs = {}
        for indice, producto in enumerate(productos):
            self.table.setItem(indice, 0, QTableWidgetItem(producto.name))
            self.table.setItem(indice, 1, QTableWidgetItem(producto.unit or ""))
            entrada = QDoubleSpinBox()
            entrada.setObjectName("stockInitialInventoryQty")
            entrada.setRange(0, 99_999_999.999)
            entrada.setDecimals(3)
            entrada.setSingleStep(25.0)
            entrada.setSuffix(" kg")
            entrada.setValue(float(cantidades.get(producto.id, 0) or 0))
            entrada.setReadOnly(bloqueado)
            entrada.setEnabled(not bloqueado)
            self.table.setCellWidget(indice, 2, entrada)
            self.inputs[producto.id] = entrada
            # Lo que dice el libro hoy. Sin esta columna el operador carga el
            # conteo y no tiene forma de verificar que haya quedado bien.
            saldo = StockService.balance_for(producto).balance_kg
            item = QTableWidgetItem(f"{saldo:,.3f}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(indice, 3, item)

    def load_inventory(self) -> None:
        dia = self.selected_date()
        quantities = {
            producto_id: Decimal(str(entrada.value()))
            for producto_id, entrada in self.inputs.items()
            if entrada.value() > 0
        }
        if not quantities:
            self.feedback.show_warning("Cargá al menos un producto con kilos.")
            return
        total = sum(quantities.values())
        answer = QMessageBox.question(
            self, "Cargar inventario inicial",
            f"¿Cargar el inventario inicial del {dia:%d/%m/%Y}?\n\n"
            f"{len(quantities)} producto(s) · {total:,.3f} kg en total.\n\n"
            "Es el punto de partida del libro de stock. Si el conteo se repite, "
            "anulá el anterior: cargar dos veces la misma fecha no reemplaza nada.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            movimientos = self.service.load_initial(
                dia, quantities,
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
            f"Inventario inicial cargado: {len(movimientos)} producto(s), {total:,.3f} kg."
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

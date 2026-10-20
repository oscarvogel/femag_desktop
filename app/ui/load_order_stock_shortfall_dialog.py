from __future__ import annotations

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.services.load_order_stock_service import StockShortfall


class LoadOrderStockShortfallDialog(QDialog):
    """Modal para avisar que la orden pide mas mercaderia de la que hay (#732).

    Muestra el faltante por producto y exige un motivo para emitir igual. El
    motivo es lo que queda asentado en la auditoria y en los movimientos del
    libro: sin el, la decision de despachar sin stock no existe.
    """

    HEADERS = ("Producto", "Stock en el libro (kg)", "Pide la orden (kg)", "Falta (kg)")

    def __init__(
        self,
        order: LoadOrder,
        faltantes: list[StockShortfall],
        parent=None,
    ):
        super().__init__(parent)
        self.order = LoadOrder.get_by_id(order.id)
        self.faltantes = list(faltantes)
        self.setObjectName("loadOrderStockShortfallDialog")
        self.setWindowTitle(f"Stock insuficiente - OC-{self.order.order_number:06d}")
        self.setModal(True)
        self.resize(720, 460)
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)

        title = QLabel(f"Stock insuficiente para la orden OC-{self.order.order_number:06d}")
        title.setObjectName("loadOrderStockShortfallTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        help_text = QLabel(
            "La orden pide más mercadería de la que hay en stock. Podés emitirla "
            "igual, pero el motivo queda registrado en la auditoría y en los "
            "movimientos de stock: es la traza de por qué se despachó sin stock."
        )
        help_text.setWordWrap(True)
        help_text.setProperty("uiRole", "muted")
        layout.addWidget(help_text)

        self.table = QTableWidget(len(self.faltantes), len(self.HEADERS))
        self.table.setObjectName("loadOrderStockShortfallTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for indice, faltante in enumerate(self.faltantes):
            valores = (
                faltante.product.name,
                f"{faltante.available_kg:,.3f}",
                f"{faltante.requested_kg:,.3f}",
                f"{faltante.missing_kg:,.3f}",
            )
            for columna, valor in enumerate(valores):
                self.table.setItem(indice, columna, QTableWidgetItem(str(valor)))
        layout.addWidget(self.table, 1)

        self.reason_input = QTextEdit()
        self.reason_input.setObjectName("loadOrderStockShortfallReasonInput")
        self.reason_input.setPlaceholderText(
            "Ej.: El cliente retiró más de lo facturado, se despacha igual y se "
            "regulariza con el próximo ingreso, error de conteo en depósito..."
        )
        self.reason_input.setMinimumHeight(110)
        layout.addWidget(self.reason_input)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("loadOrderStockShortfallValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText("Cancelar")
        self.cancel_button.setObjectName("loadOrderStockShortfallCancelButton")
        self.issue_button = buttons.button(QDialogButtonBox.Ok)
        self.issue_button.setText("Despachar igual")
        self.issue_button.setObjectName("loadOrderStockShortfallConfirmButton")
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)

        self.reason_input.setFocus()

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()

    def _validate_and_accept(self) -> None:
        if not self.reason():
            self.validation_label.setText(
                "Debe indicar el motivo por el que se despacha sin stock suficiente."
            )
            self.reason_input.setFocus()
            return
        self.validation_label.clear()
        self.accept()


def emit_order_with_stock_check(operation_service, order, *, parent=None):
    """Emite la orden, pidiendo motivo si no hay stock suficiente (#732).

    Devuelve la orden emitida, o ``None`` si el operador cancelo: en ese caso
    no se toco ningun libro.

    Vive aca y no duplicado en cada pantalla porque hay **dos** pantallas de
    ordenes de carga (la del base y la de la extension que se instala en
    ``app/main.py``), y las dos tienen que avisar igual. Si solo avisara una,
    el faltante pasaria segun cual se este usando.
    """
    from app.services.load_order_operation_service import LoadOrderStockShortfallError

    try:
        return operation_service.issue(order)
    except LoadOrderStockShortfallError as exc:
        dialog = LoadOrderStockShortfallDialog(order, exc.faltantes, parent=parent)
        if dialog.exec_() != QDialog.Accepted:
            return None
        return operation_service.issue(order, stock_override_reason=dialog.reason())

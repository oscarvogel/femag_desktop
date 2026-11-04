"""Dialogo para corregir lote y fechas por contenido de una orden (#864)."""

from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.services.load_order_traceability_service import (
    LINE,
    LOOSE_CONTENT,
    PALLET_CONTENT,
    LoadOrderTraceabilityError,
    LoadOrderTraceabilityService,
)

NO_DATE = QDate(1900, 1, 1)


def load_order_traceability_rows(order: LoadOrder) -> list[dict]:
    order = LoadOrder.get_by_id(order.id)
    rows: list[dict] = []

    pallet_allocations = list(
        LoadOrderPalletAllocation.select()
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence, LoadOrderPalletAllocation.id)
    )
    for allocation in pallet_allocations:
        rows.append(
            _row(
                kind=PALLET_CONTENT,
                item_id=allocation.id,
                content=f"Pallet {allocation.pallet.sequence}",
                destination=allocation.destination,
                product=allocation.product,
                quantity=allocation.quantity,
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
            )
        )

    loose_allocations = list(
        LoadOrderLooseAllocation.select()
        .where(LoadOrderLooseAllocation.order == order)
        .order_by(LoadOrderLooseAllocation.id)
    )
    for allocation in loose_allocations:
        rows.append(
            _row(
                kind=LOOSE_CONTENT,
                item_id=allocation.id,
                content="Suelto",
                destination=allocation.destination,
                product=allocation.product,
                quantity=allocation.quantity,
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
            )
        )

    if rows:
        return rows

    # Orden legacy sin composicion: se edita directamente el renglon.
    for line in (
        LoadOrderProduct.select()
        .where(LoadOrderProduct.order == order)
        .order_by(LoadOrderProduct.id)
    ):
        rows.append(
            _row(
                kind=LINE,
                item_id=line.id,
                content="Renglon",
                destination=line.destination,
                product=line.product,
                quantity=line.quantity,
                lote=line.lote,
                fecha_elaboracion=line.fecha_elaboracion,
                fecha_envasado=line.fecha_envasado,
            )
        )
    return rows


def _row(
    *,
    kind: str,
    item_id: int,
    content: str,
    destination,
    product,
    quantity,
    lote,
    fecha_elaboracion,
    fecha_envasado,
) -> dict:
    client_name = ""
    destination_label = ""
    if destination is not None:
        client_name = destination.client.name
        address = destination.delivery_address
        if address is not None:
            destination_label = " - ".join(
                part for part in (address.address, address.city) if part
            )
    return {
        "kind": kind,
        "id": item_id,
        "content": content,
        "client": client_name,
        "destination": destination_label,
        "product": product.name if product is not None else "",
        "quantity": quantity,
        "lote": lote,
        "fecha_elaboracion": fecha_elaboracion,
        "fecha_envasado": fecha_envasado,
    }


class LoadOrderTraceabilityDialog(QDialog):
    def __init__(
        self,
        service: LoadOrderTraceabilityService,
        order: LoadOrder,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.order = LoadOrder.get_by_id(order.id)
        self.updated_count = 0
        self.setObjectName("loadOrderTraceabilityDialog")
        self.setWindowTitle(
            f"Lote / fecha OC-{self.order.order_number:06d}"
        )
        self.setModal(True)
        self.resize(1080, 520)
        self.setMinimumWidth(900)

        layout = QVBoxLayout(self)

        title = QLabel(f"Lote / fecha - OC-{self.order.order_number:06d}")
        title.setObjectName("loadOrderTraceabilityTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Corrija el lote y las fechas de cada contenido. El cliente, el "
            "destino, el producto y la cantidad no se modifican."
        )
        hint.setWordWrap(True)
        hint.setProperty("uiRole", "muted")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("loadOrderTraceabilityTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Contenido",
                "Cliente",
                "Destino",
                "Producto",
                "Cant.",
                "Lote",
                "Elaboracion",
                "Envasado",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((90, 160, 170, 160, 70, 150, 120, 120)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)

        self.reason_input = None
        if self.order.status == LoadOrder.STATUS_CLOSED:
            reason_label = QLabel("Motivo del cambio (obligatorio en orden cerrada)")
            reason_label.setProperty("uiRole", "muted")
            layout.addWidget(reason_label)
            self.reason_input = QTextEdit()
            self.reason_input.setObjectName("loadOrderTraceabilityReasonInput")
            self.reason_input.setPlaceholderText(
                "Indique por que se corrige el lote o las fechas."
            )
            self.reason_input.setFixedHeight(70)
            layout.addWidget(self.reason_input)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("loadOrderTraceabilityValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText("Cancelar")
        self.cancel_button.setObjectName("loadOrderTraceabilityCancelButton")
        self.save_button = buttons.button(QDialogButtonBox.Ok)
        self.save_button.setText("Guardar cambios")
        self.save_button.setObjectName("loadOrderTraceabilitySaveButton")
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)

        self._populate()

    def _populate(self) -> None:
        rows = load_order_traceability_rows(self.order)
        self.table.setRowCount(len(rows))
        self._editors: list[dict] = []
        for index, row in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(row["content"]))
            self.table.setItem(index, 1, QTableWidgetItem(row["client"]))
            self.table.setItem(index, 2, QTableWidgetItem(row["destination"]))
            self.table.setItem(index, 3, QTableWidgetItem(row["product"]))
            self.table.setItem(index, 4, QTableWidgetItem(f"{float(row['quantity']):g}"))

            lote_edit = QLineEdit(row["lote"] or "")
            lote_edit.setObjectName(f"loadOrderTraceabilityLote_{index}")
            self.table.setCellWidget(index, 5, lote_edit)

            elab_edit = self._date_edit(row["fecha_elaboracion"])
            elab_edit.setObjectName(f"loadOrderTraceabilityElab_{index}")
            self.table.setCellWidget(index, 6, elab_edit)

            envasado_edit = self._date_edit(row["fecha_envasado"])
            envasado_edit.setObjectName(f"loadOrderTraceabilityEnvasado_{index}")
            self.table.setCellWidget(index, 7, envasado_edit)

            self._editors.append(
                {
                    "row": row,
                    "lote": lote_edit,
                    "elaboracion": elab_edit,
                    "envasado": envasado_edit,
                }
            )

    @staticmethod
    def _date_edit(value) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd/MM/yyyy")
        edit.setMinimumDate(NO_DATE)
        edit.setSpecialValueText("-")
        if value is None:
            edit.setDate(NO_DATE)
        else:
            edit.setDate(QDate(value.year, value.month, value.day))
        return edit

    @staticmethod
    def _date_value(edit: QDateEdit):
        value = edit.date()
        if value == NO_DATE:
            return None
        return value.toPyDate()

    def reason(self) -> str:
        if self.reason_input is None:
            return ""
        return self.reason_input.toPlainText().strip()

    def items(self) -> list[dict]:
        return [
            {
                "kind": editor["row"]["kind"],
                "id": editor["row"]["id"],
                "lote": editor["lote"].text().strip(),
                "fecha_elaboracion": self._date_value(editor["elaboracion"]),
                "fecha_envasado": self._date_value(editor["envasado"]),
            }
            for editor in self._editors
        ]

    def _save(self) -> None:
        self.validation_label.clear()
        if self.reason_input is not None and not self.reason():
            self.validation_label.setText(
                "Debe indicar el motivo del cambio en una orden cerrada."
            )
            self.reason_input.setFocus()
            return
        try:
            self.updated_count = self.service.update_lote_fecha(
                self.order,
                self.items(),
                reason=self.reason(),
            )
        except (LoadOrderTraceabilityError, ValueError) as exc:
            self.validation_label.setText(str(exc))
            return
        self.accept()


__all__ = [
    "LoadOrderTraceabilityDialog",
    "load_order_traceability_rows",
]

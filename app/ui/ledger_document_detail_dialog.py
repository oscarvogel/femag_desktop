from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget
from app.models.payments import ClientPayment, ClientPaymentDetail


def _money(value) -> str:
    return f"$ {float(value or 0):,.2f}"


def _date(value) -> str:
    return value.strftime("%d/%m/%Y") if value is not None else ""


class LedgerDocumentDetailDialog(QDialog):
    """Read-only detail for the source document of a ledger movement."""

    def __init__(self, movement: ClientAccountMovement, parent=None):
        super().__init__(parent)
        self.movement = ClientAccountMovement.get_by_id(movement.id)
        self.document_type, self.document = self.resolve_document(self.movement)
        if self.document is None:
            raise ValueError("El movimiento no tiene un documento asociado disponible.")

        self.setObjectName("ledgerDocumentDetailDialog")
        self.setModal(True)
        self.resize(900, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        if self.document_type == "budget":
            self._build_budget(layout, self.document)
        else:
            self._build_payment(layout, self.document)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("ledgerDocumentDetailCloseButton")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    @classmethod
    def _source_movement(cls, movement: ClientAccountMovement | None):
        if movement is None:
            return None
        if movement.budget_id is not None or movement.payment_id is not None:
            return movement
        if movement.reverses_id is not None:
            return movement.reverses
        return movement

    @classmethod
    def resolve_document(
        cls, movement: ClientAccountMovement | None
    ) -> tuple[str | None, Budget | ClientPayment | None]:
        source = cls._source_movement(movement)
        if source is None:
            return None, None

        if source.budget_id is not None:
            return "budget", Budget.get_or_none(Budget.id == source.budget_id)
        if source.payment_id is not None:
            return "payment", ClientPayment.get_or_none(ClientPayment.id == source.payment_id)

        source_ref = str(source.source_ref or "")
        if source_ref.startswith("Budget:"):
            try:
                budget_id = int(source_ref.split(":", 1)[1])
            except (TypeError, ValueError):
                budget_id = None
            if budget_id is not None:
                budget = Budget.get_or_none(Budget.id == budget_id)
                if budget is not None:
                    return "budget", budget
        return None, None

    @classmethod
    def supports(cls, movement: ClientAccountMovement | None) -> bool:
        _kind, document = cls.resolve_document(movement)
        return document is not None

    def _title(self, text: str, subtitle: str) -> tuple[QLabel, QLabel]:
        title = QLabel(text)
        title.setObjectName("dialogTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("ledgerDocumentDetailSubtitle")
        subtitle_label.setWordWrap(True)
        return title, subtitle_label

    def _info_card(self) -> tuple[QFrame, QFormLayout]:
        card = QFrame()
        card.setObjectName("ledgerDocumentDetailInfoCard")
        form = QFormLayout(card)
        form.setContentsMargins(14, 12, 14, 12)
        form.setSpacing(8)
        return card, form

    @staticmethod
    def _add_row(form: QFormLayout, label: str, value: str) -> QLabel:
        value_label = QLabel(value or "—")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow(label, value_label)
        return value_label

    def _build_budget(self, layout: QVBoxLayout, budget: Budget) -> None:
        self.setWindowTitle(f"Detalle de presupuesto {budget.display_number}")
        title, subtitle = self._title(
            f"Presupuesto {budget.display_number}",
            "Detalle completo del presupuesto asociado al movimiento de cuenta corriente.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card, form = self._info_card()
        self._add_row(form, "Cliente", budget.client.name)
        self._add_row(form, "Fecha", _date(budget.issue_date))
        self._add_row(
            form,
            "Estado",
            "Activo" if budget.status == Budget.STATUS_ACTIVE else "Anulado",
        )
        self._add_row(
            form,
            "Origen",
            "Manual" if budget.origin == Budget.ORIGIN_MANUAL else "Orden de carga",
        )
        self._add_row(form, "Orden de carga", budget.load_order_reference or "—")
        self._add_row(form, "Neto", _money(budget.net_amount))
        self._add_row(form, "Descuento", _money(budget.discount_amount))
        self._add_row(form, "IVA", _money(budget.vat_amount))
        self.budget_total_label = self._add_row(form, "Total", _money(budget.total_amount))
        self._add_row(form, "Observaciones", budget.observations or "—")
        layout.addWidget(card)

        self.detail_table = QTableWidget(0, 8)
        self.detail_table.setObjectName("ledgerBudgetDetailTable")
        self.detail_table.setHorizontalHeaderLabels(
            ["Producto", "Cantidad", "Unidad", "P. unitario", "Desc.", "Neto", "IVA", "Total"]
        )
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setAlternatingRowColors(True)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)

        items = list(budget.items.order_by())
        self.detail_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (
                item.product.name,
                self._quantity(item.quantity),
                item.unit or "",
                _money(item.unit_price),
                f"{float(item.discount_percentage or 0):.2f}%",
                _money(item.net_taxable),
                _money(item.vat_amount),
                _money(item.total),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setToolTip(value)
                self.detail_table.setItem(row, column, cell)
        layout.addWidget(self.detail_table, 1)

    def _build_payment(self, layout: QVBoxLayout, payment: ClientPayment) -> None:
        self.setWindowTitle(f"Detalle de recibo {payment.receipt_number}")
        title, subtitle = self._title(
            f"Recibo {payment.receipt_number}",
            "Detalle completo del pago asociado al movimiento de cuenta corriente.",
        )
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card, form = self._info_card()
        self._add_row(form, "Cliente", payment.client.name)
        self._add_row(form, "Fecha", _date(payment.payment_date))
        self._add_row(
            form,
            "Estado",
            "Activo" if payment.status == ClientPayment.STATUS_ACTIVE else "Anulado",
        )
        self.payment_total_label = self._add_row(form, "Importe", _money(payment.amount))
        self._add_row(form, "Medio", self._payment_method_label(payment))
        self._add_row(form, "Referencia", payment.reference or "—")
        self._add_row(form, "Observaciones", payment.observations or "—")
        if payment.status == ClientPayment.STATUS_ANNULLED:
            self._add_row(form, "Motivo anulación", payment.annulment_reason or "—")
            self._add_row(form, "Anulado por", payment.annulled_by or "—")
        layout.addWidget(card)

        self.detail_table = QTableWidget(0, 4)
        self.detail_table.setObjectName("ledgerPaymentDetailTable")
        self.detail_table.setHorizontalHeaderLabels(
            ["Medio de pago", "Referencia", "Observaciones", "Importe"]
        )
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setAlternatingRowColors(True)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        details = list(
            ClientPaymentDetail.select()
            .where(ClientPaymentDetail.payment == payment)
            .order_by(ClientPaymentDetail.sequence)
        )
        self.detail_table.setRowCount(len(details))
        for row, detail in enumerate(details):
            values = (
                detail.payment_method.name,
                detail.reference or "",
                detail.observations or "",
                _money(detail.amount),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 3:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell.setToolTip(value)
                self.detail_table.setItem(row, column, cell)
        layout.addWidget(self.detail_table, 1)

    @staticmethod
    def _payment_method_label(payment: ClientPayment) -> str:
        if payment.method == "multiple":
            return "Múltiples medios"
        detail = (
            ClientPaymentDetail.select()
            .where(ClientPaymentDetail.payment == payment)
            .order_by(ClientPaymentDetail.sequence)
            .first()
        )
        if detail is not None:
            return detail.payment_method.name
        return payment.method or "—"

    @staticmethod
    def _quantity(value: float) -> str:
        numeric = float(value or 0)
        return f"{numeric:.0f}" if numeric.is_integer() else f"{numeric:.3f}".rstrip("0").rstrip(".")

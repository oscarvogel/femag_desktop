"""Diálogo de administración para reparar órdenes de carga emitidas a medias.

Una orden emitida tiene que estar en la cuenta corriente del cliente y tener su
mercadería descontada del stock. Desde #726 eso no puede fallar: la emisión es
una sola transacción.

Este diálogo es para lo que ya quedó roto antes de la garantía: lista las
órdenes emitidas o cerradas que no tienen movimiento en la cuenta corriente o
salida de stock, y deja repararlas de a una, con la confirmación de lo que se va
a registrar antes de escribir.

Es una herramienta de administración: sólo un administrador la abre.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.services.load_order_ledger_repair_service import (
    LoadOrderLedgerRepairService,
    OrderLedgerGap,
)
from app.services.permission_service import PermissionService


def _money(value: float) -> str:
    return f"{value:,.2f}"


class LoadOrderLedgerRepairDialog(QDialog):
    """Lista las órdenes con faltantes y permite repararlas de a una."""

    def __init__(
        self,
        current_user: str,
        parent=None,
        *,
        user=None,
        repair_service: LoadOrderLedgerRepairService | None = None,
    ):
        super().__init__(parent)
        self.current_user = current_user
        self.user = user
        self.repair_service = repair_service or LoadOrderLedgerRepairService(current_user)
        self.findings: list[OrderLedgerGap] = []
        self.repaired: list[str] = []
        self.setObjectName("loadOrderLedgerRepairDialog")
        self.setWindowTitle("Reparar cuenta corriente de órdenes emitidas")
        self.resize(1000, 620)
        self.setMinimumSize(820, 480)
        self._build()

    # -- Construcción ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Órdenes emitidas sin cuenta corriente o sin salida de stock")
        title.setObjectName("loadOrderLedgerRepairTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Una orden emitida tiene que estar en la cuenta corriente del cliente y con la "
            "mercadería descontada del stock. Si a una orden le falta algo, la reparación "
            "registra el documento con el importe del presupuesto ya emitido: no cambia "
            "importes ni rehace la operación física."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("loadOrderLedgerRepairTable")
        self.table.setHorizontalHeaderLabels(
            ["Orden", "Fecha", "Estado", "Documentos a registrar", "Falta", "Importe"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for column, width in enumerate((110, 100, 100, 330, 240, 150)):
            self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        self.detail = QLabel("")
        self.detail.setObjectName("loadOrderLedgerRepairDetail")
        self.detail.setWordWrap(True)
        self.detail.setProperty("uiRole", "muted")
        layout.addWidget(self.detail)

        self.repair_button = QPushButton("Reparar la orden seleccionada")
        self.repair_button.setObjectName("loadOrderLedgerRepairButton")
        self.repair_button.clicked.connect(self._repair_selected)
        self.repair_button.setEnabled(False)

        close_button = QPushButton("Cerrar")
        close_button.setObjectName("loadOrderLedgerRepairCloseButton")
        close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.repair_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.reload()

    # -- Datos -------------------------------------------------------------
    def reload(self) -> None:
        """Vuelve a listar las órdenes con faltantes."""
        self.findings = self.repair_service.find_broken_orders()
        self.table.setRowCount(0)
        for row, finding in enumerate(self.findings):
            self.table.insertRow(row)
            documentos = ", ".join(
                f"{gap.budget_number} ({gap.client_name})" for gap in finding.ledger_gaps
            ) or "—"
            valores = (
                f"OC-{finding.order_number:06d}",
                finding.date,
                finding.status,
                documentos,
                finding.summary(),
                _money(finding.total_amount),
            )
            for column, value in enumerate(valores):
                item = QTableWidgetItem(value)
                if column in (0, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        if self.findings:
            self.table.selectRow(0)
        self._update_buttons()

    def _selected_finding(self) -> OrderLedgerGap | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.findings):
            return None
        return self.findings[row]

    def _update_buttons(self) -> None:
        finding = self._selected_finding()
        puede = bool(finding and finding.is_repairable) and PermissionService.is_administrator(
            self.user
        )
        self.repair_button.setEnabled(puede)
        if finding is None:
            self.detail.setText("")
            return
        lineas = [f"{finding.order_reference}: se va a registrar lo siguiente."]
        for gap in finding.ledger_gaps:
            lineas.append(
                f"• {gap.budget_number} · {gap.client_name} · {_money(gap.total_amount)}"
            )
        if finding.missing_stock:
            lineas.append(
                f"• Salida de stock: {finding.stock_units} unidad(es) / {finding.stock_kg:,.0f} kg"
            )
        self.detail.setText("\n".join(lineas))

    # -- Acción ------------------------------------------------------------
    def _repair_selected(self) -> None:
        finding = self._selected_finding()
        if finding is None:
            return
        if not PermissionService.is_administrator(self.user):
            QMessageBox.warning(
                self,
                "Reparar cuenta corriente",
                "Sólo un administrador puede reparar órdenes emitidas.",
            )
            return

        textos = []
        for gap in finding.ledger_gaps:
            textos.append(f"• {gap.budget_number} — {gap.client_name} — {_money(gap.total_amount)}")
        if finding.missing_stock:
            textos.append(
                f"• Salida de stock — {finding.stock_units} unidad(es) / {finding.stock_kg:,.0f} kg"
            )
        detalle = "\n".join(textos) or "nada pendiente"

        confirmado = QMessageBox.question(
            self,
            "Reparar cuenta corriente",
            f"Se va a registrar en la cuenta corriente de {finding.order_reference}:\n\n"
            f"{detalle}\n\n"
            "Los importes son los del presupuesto ya emitido. ¿Confirmás?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmado != QMessageBox.Yes:
            return

        order = LoadOrder.get_by_id(finding.order_id)
        try:
            result = self.repair_service.repair(order)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Reparar cuenta corriente",
                f"No se pudo registrar. No se modificó nada:\n\n{exc}",
            )
            self.reload()
            return

        self.repaired.append(result.order_reference)
        QMessageBox.information(
            self,
            "Reparar cuenta corriente",
            f"{result.order_reference} registrada.\n\n"
            f"Movimientos de cuenta corriente: {len(result.movement_ids)}\n"
            f"Movimientos de stock: {len(result.stock_movement_ids)}",
        )
        self.reload()

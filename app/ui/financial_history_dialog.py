from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget
from app.services.audit_history_service import AuditHistoryEvent, AuditHistoryService


class FinancialHistoryDialog(QDialog):
    def __init__(
        self,
        movement: ClientAccountMovement,
        parent=None,
        *,
        history_service: AuditHistoryService | None = None,
    ):
        super().__init__(parent)
        self.movement = ClientAccountMovement.get_by_id(movement.id)
        self.history_service = history_service or AuditHistoryService()
        self.title_text, self.events = self._resolve_history()
        self.setObjectName("financialHistoryDialog")
        self.setWindowTitle(self.title_text)
        self.resize(940, 560)
        self.setMinimumSize(760, 420)
        self._build()

    @classmethod
    def supports(cls, movement: ClientAccountMovement | None) -> bool:
        if movement is None:
            return False
        if movement.payment_id is not None or movement.budget_id is not None:
            return True
        if movement.movement_type in {
            ClientAccountMovement.TYPE_MANUAL_DEBIT,
            ClientAccountMovement.TYPE_MANUAL_DEBIT_REVERSAL,
            ClientAccountMovement.TYPE_MANUAL_CREDIT,
            ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL,
        }:
            return True
        source_ref = str(movement.source_ref or "")
        return source_ref.startswith("Budget:")

    def _resolve_history(self) -> tuple[str, list[AuditHistoryEvent]]:
        movement = self.movement
        if movement.payment_id is not None:
            payment = movement.payment
            return (
                f"Historial del recibo {payment.receipt_number}",
                self.history_service.payment_history(payment),
            )

        budget = None
        if movement.budget_id is not None:
            budget = movement.budget
        else:
            source_ref = str(movement.source_ref or "")
            if source_ref.startswith("Budget:"):
                try:
                    budget_id = int(source_ref.split(":", 1)[1])
                except (TypeError, ValueError):
                    budget_id = None
                if budget_id is not None:
                    budget = Budget.get_or_none(Budget.id == budget_id)
        if budget is not None:
            return (
                f"Historial del presupuesto {budget.display_number}",
                self.history_service.budget_history(budget),
            )

        return (
            "Historial del movimiento",
            self.history_service.account_movement_history(movement),
        )

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(self.title_text)
        title.setObjectName("financialHistoryTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Trazabilidad cronológica de creación, impresión, anulación o reverso."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(subtitle)

        table = QTableWidget(len(self.events), 5)
        table.setObjectName("financialHistoryTable")
        table.setHorizontalHeaderLabels(
            ["Fecha y hora", "Usuario", "Acción", "Evolución", "Motivo / detalle"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)

        for row_index, event in enumerate(self.events):
            for column, value in enumerate(self._row_values(event)):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                table.setItem(row_index, column, item)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(table, 1)

        if not self.events:
            empty = QLabel("Todavía no hay eventos de auditoría para este movimiento.")
            empty.setObjectName("financialHistoryEmptyLabel")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("closeFinancialHistoryButton")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    @staticmethod
    def _row_values(event: AuditHistoryEvent) -> tuple[str, str, str, str, str]:
        occurred = event.occurred_at
        if getattr(occurred, "tzinfo", None) is not None:
            occurred = occurred.astimezone()
        transition = ""
        if event.previous_status or event.new_status:
            transition = f"{event.previous_status or '—'} → {event.new_status or '—'}"
        detail_parts = [part for part in (event.reason, event.detail) if part]
        return (
            occurred.strftime("%d/%m/%Y %H:%M"),
            event.user or "Sistema",
            event.action,
            transition,
            " · ".join(detail_parts),
        )

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

from app.models.remittances import Remittance
from app.services.audit_history_service import AuditHistoryEvent, AuditHistoryService


class RemittanceHistoryDialog(QDialog):
    def __init__(
        self,
        remittance: Remittance,
        parent=None,
        *,
        history_service: AuditHistoryService | None = None,
    ):
        super().__init__(parent)
        self.remittance = Remittance.get_by_id(remittance.id)
        self.history_service = history_service or AuditHistoryService()
        self.events = self.history_service.remittance_history(self.remittance)

        self.setObjectName("remittanceHistoryDialog")
        self.setWindowTitle(f"Historial {self.remittance.remittance_number}")
        self.resize(940, 560)
        self.setMinimumSize(760, 420)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(f"Historial {self.remittance.remittance_number}")
        title.setObjectName("remittanceHistoryTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Trazabilidad cronológica de creación, modificaciones, emisión y anulación."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(subtitle)

        table = QTableWidget(len(self.events), 5)
        table.setObjectName("remittanceHistoryTable")
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

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton("Cerrar")
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

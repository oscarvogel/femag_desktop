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

from app.models.load_orders import LoadOrder
from app.services.audit_history_service import AuditHistoryEvent, AuditHistoryService
from app.utils.datetime_utils import utc_datetime_to_local


class LoadOrderHistoryDialog(QDialog):
    def __init__(
        self,
        order: LoadOrder,
        parent=None,
        *,
        history_service: AuditHistoryService | None = None,
    ):
        super().__init__(parent)
        self.order = LoadOrder.get_by_id(order.id)
        self.history_service = history_service or AuditHistoryService()
        self.setObjectName("loadOrderHistoryDialog")
        self.setWindowTitle(f"Historial de orden #{self.order.order_number:06d}")
        self.resize(940, 560)
        self.setMinimumSize(760, 420)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel(f"Historial de orden #{self.order.order_number:06d}")
        title.setObjectName("loadOrderHistoryTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Trazabilidad cronológica de creación, cambios de estado y acciones registradas."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("uiRole", "muted")
        layout.addWidget(subtitle)

        events = self.history_service.load_order_history(self.order)
        table = QTableWidget(len(events), 5)
        table.setObjectName("loadOrderHistoryTable")
        table.setHorizontalHeaderLabels(
            ["Fecha y hora", "Usuario", "Acción", "Evolución", "Motivo / detalle"]
        )
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)

        for row_index, event in enumerate(events):
            values = self._row_values(event)
            for column, value in enumerate(values):
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

        if not events:
            empty = QLabel("Todavía no hay eventos de auditoría para esta orden.")
            empty.setObjectName("loadOrderHistoryEmptyLabel")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("closeLoadOrderHistoryButton")
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    @staticmethod
    def _row_values(event: AuditHistoryEvent) -> tuple[str, str, str, str, str]:
        occurred = utc_datetime_to_local(event.occurred_at)
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

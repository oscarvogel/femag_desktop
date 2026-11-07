from __future__ import annotations

import webbrowser

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.services.managerial_summary_service import (
    ManagerialDeliveryConfig,
    ManagerialSummaryService,
)
from app.utils.datetime_utils import utc_datetime_to_local


class ManagerialSummarySendDialog(QDialog):
    def __init__(self, *, service: ManagerialSummaryService | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("managerialSummarySendDialog")
        self.setWindowTitle("Enviar resumen gerencial")
        self.resize(800, 580)
        self.setMinimumSize(680, 500)
        self.service = service or ManagerialSummaryService()
        self.summary = self.service.build()
        config = ManagerialDeliveryConfig.from_env()

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Resumen gerencial al {self.summary.as_of:%d/%m/%Y}"))

        form = QFormLayout()
        self.email_check = QCheckBox("Enviar por email")
        self.email_check.setChecked(bool(config.email))
        self.email_input = QLineEdit(config.email)
        self.email_input.setObjectName("managerialSummaryEmail")
        self.whatsapp_check = QCheckBox("Enviar por WhatsApp")
        self.whatsapp_check.setChecked(bool(config.phone))
        self.phone_input = QLineEdit(config.phone)
        self.phone_input.setObjectName("managerialSummaryWhatsapp")
        self.instance_input = QLineEdit(config.whatsapp_instance_id)
        self.instance_input.setObjectName("managerialSummaryWhatsappInstance")
        self.instance_input.setPlaceholderText("Ej.: vogel_consultoria")

        form.addRow(self.email_check, self.email_input)
        form.addRow(self.whatsapp_check, self.phone_input)
        form.addRow("Instancia WhatsApp gerencial", self.instance_input)
        root.addLayout(form)

        note = QLabel(
            "La instancia indicada aquí es explícita para el resumen gerencial y no usa "
            "la instancia WhatsApp asociada al usuario actual."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        history_label = QLabel("Últimos envíos")
        history_label.setObjectName("managerialSummaryHistoryLabel")
        root.addWidget(history_label)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setObjectName("managerialSummaryHistory")
        self.history_table.setHorizontalHeaderLabels(
            ["Fecha", "Canal", "Estado", "Gateway", "Error"]
        )
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setMinimumHeight(220)
        self.history_table.setMaximumHeight(300)
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.history_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.history_table, 1)
        self._load_history()

        self.status_label = QLabel("")
        self.status_label.setObjectName("managerialSummarySendStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        preview = QPushButton("Vista previa")
        preview.setObjectName("managerialSummaryPreviewButton")
        preview.clicked.connect(self._preview)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        send = QPushButton("Enviar ahora")
        send.setObjectName("managerialSummarySendNowButton")
        send.clicked.connect(self._send)
        actions.addWidget(preview)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(send)
        root.addLayout(actions)

    def _preview(self) -> None:
        path = self.service.write_preview(self.summary)
        webbrowser.open(path.resolve().as_uri())

    def _load_history(self) -> None:
        labels = {
            "sent": "Enviado",
            "accepted": "Aceptado por gateway",
            "failed": "Fallido",
            "unknown": "Sin confirmar",
            "pending": "Pendiente",
            "queued": "Encolado",
            "processing": "Procesando",
        }
        rows = self.service.recent_deliveries(limit=10)
        self.history_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            created = utc_datetime_to_local(row.created_at)
            values = [
                created.strftime("%d/%m/%Y %H:%M") if created else "",
                row.channel or "",
                labels.get(row.status, row.status or ""),
                row.provider_status or "",
                row.error or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if value:
                    item.setToolTip(str(value))
                self.history_table.setItem(row_index, column, item)
        self.history_table.resizeColumnsToContents()
        self.history_table.horizontalHeader().setStretchLastSection(True)

    def _send(self) -> None:
        if not self.email_check.isChecked() and not self.whatsapp_check.isChecked():
            QMessageBox.warning(self, "Resumen gerencial", "Seleccione al menos un canal de envío.")
            return

        results: list[str] = []
        errors: list[str] = []

        if self.email_check.isChecked():
            try:
                recipient = self.email_input.text().strip()
                self.service.send_email(self.summary, recipient=recipient)
                self.service.record_delivery(mode="manual", channel="email", recipient=recipient, status="sent")
                results.append("Email: enviado")
            except Exception as exc:
                recipient = self.email_input.text().strip()
                self.service.record_delivery(mode="manual", channel="email", recipient=recipient, status="failed", error=str(exc))
                errors.append(f"Email: {exc}")

        if self.whatsapp_check.isChecked():
            try:
                recipient = self.phone_input.text().strip()
                response = self.service.send_whatsapp(
                    self.summary,
                    phone=recipient,
                    instance_id=self.instance_input.text(),
                )
                self.service.record_delivery(
                    mode="manual",
                    channel="whatsapp",
                    recipient=recipient,
                    status=str(response.get("status") or "accepted"),
                    provider_message_id=response.get("messageId"),
                )
                results.append("WhatsApp: aceptado por gateway")
            except Exception as exc:
                recipient = self.phone_input.text().strip()
                self.service.record_delivery(mode="manual", channel="whatsapp", recipient=recipient, status="failed", error=str(exc))
                errors.append(f"WhatsApp: {exc}")

        message = "\n".join(results + errors)
        self.status_label.setText(message)
        self._load_history()
        if errors:
            QMessageBox.warning(self, "Resumen gerencial", message)
        else:
            QMessageBox.information(self, "Resumen gerencial", message)

from __future__ import annotations

import webbrowser

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.services.managerial_summary_service import (
    ManagerialDeliveryConfig,
    ManagerialSummaryService,
)


class ManagerialSummarySendDialog(QDialog):
    def __init__(self, *, service: ManagerialSummaryService | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("managerialSummarySendDialog")
        self.setWindowTitle("Enviar resumen gerencial")
        self.resize(620, 360)
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

    def _send(self) -> None:
        if not self.email_check.isChecked() and not self.whatsapp_check.isChecked():
            QMessageBox.warning(self, "Resumen gerencial", "Seleccione al menos un canal de envío.")
            return

        results: list[str] = []
        errors: list[str] = []

        if self.email_check.isChecked():
            try:
                self.service.send_email(self.summary, recipient=self.email_input.text())
                results.append("Email: enviado")
            except Exception as exc:
                errors.append(f"Email: {exc}")

        if self.whatsapp_check.isChecked():
            try:
                self.service.send_whatsapp(
                    self.summary,
                    phone=self.phone_input.text(),
                    instance_id=self.instance_input.text(),
                )
                results.append("WhatsApp: aceptado por gateway")
            except Exception as exc:
                errors.append(f"WhatsApp: {exc}")

        message = "\n".join(results + errors)
        self.status_label.setText(message)
        if errors:
            QMessageBox.warning(self, "Resumen gerencial", message)
        else:
            QMessageBox.information(self, "Resumen gerencial", message)

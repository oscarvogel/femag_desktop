from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.services.whatsapp_envio_service import WhatsAppEnvioService, normalize_phone
from app.ui.form_feedback import FormFeedback


class WhatsAppSendDialog(QDialog):
    def __init__(self, *, client_name: str, phone: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enviar extracto por WhatsApp")
        self.setObjectName("whatsappSendDialog")
        self.resize(560, 330)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Cliente: {client_name}"))

        form = QFormLayout()
        self.phone_input = QLineEdit(phone or "")
        self.phone_input.setObjectName("whatsappPhoneInput")
        self.phone_input.setPlaceholderText("Ej.: +54 9 3743 123456")
        self.caption_input = QTextEdit(
            f"Hola {client_name}, le compartimos su extracto de cuenta corriente de FEMAG."
        )
        self.caption_input.setObjectName("whatsappCaptionInput")
        self.caption_input.setMaximumHeight(100)
        form.addRow("Número", self.phone_input)
        form.addRow("Mensaje", self.caption_input)
        root.addLayout(form)

        self.normalized_label = QLabel("")
        self.normalized_label.setObjectName("whatsappNormalizedPhone")
        root.addWidget(self.normalized_label)
        self.feedback = FormFeedback("whatsappSendFeedback")
        root.addWidget(self.feedback)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        send = QPushButton("Enviar PDF")
        send.setObjectName("confirmWhatsAppSendButton")
        cancel.clicked.connect(self.reject)
        send.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(send)
        root.addLayout(actions)

        self.phone_input.textChanged.connect(self._preview_phone)
        self._preview_phone()

    def _preview_phone(self) -> None:
        try:
            phone = normalize_phone(self.phone_input.text())
        except ValueError:
            self.normalized_label.setText("Número final: —")
        else:
            self.normalized_label.setText(f"Número final: +{phone}")

    def _confirm(self) -> None:
        try:
            normalize_phone(self.phone_input.text())
        except ValueError as exc:
            self.feedback.show_warning(str(exc), focus_widget=self.phone_input)
            return
        if not self.caption_input.toPlainText().strip():
            self.feedback.show_warning("Ingrese un mensaje para acompañar el PDF.", focus_widget=self.caption_input)
            return
        self.accept()

    def phone(self) -> str:
        return self.phone_input.text().strip()

    def caption(self) -> str:
        return self.caption_input.toPlainText().strip()


class WhatsAppWorkerSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


class WhatsAppSendWorker(QRunnable):
    def __init__(self, *, envio_id: int, pdf_path: Path, service: WhatsAppEnvioService | None = None):
        super().__init__()
        self.envio_id = envio_id
        self.pdf_path = Path(pdf_path)
        self.service = service or WhatsAppEnvioService()
        self.signals = WhatsAppWorkerSignals()

    def run(self) -> None:
        from app.models.whatsapp import WhatsAppEnvio

        try:
            envio = WhatsAppEnvio.get_by_id(self.envio_id)
            result = self.service.send_pdf(envio=envio, pdf_path=self.pdf_path)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()

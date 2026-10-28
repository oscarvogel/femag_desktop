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
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.services.whatsapp_envio_service import WhatsAppEnvioService, normalize_phone
from app.services.whatsapp_phone_classifier import clasificar_telefono
from app.ui.form_feedback import FormFeedback


class WhatsAppSendDialog(QDialog):
    def __init__(
        self,
        *,
        client_name: str,
        phone: str,
        default_message: str | None = None,
        window_title: str = "Enviar extracto por WhatsApp",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setObjectName("whatsappSendDialog")
        self.resize(560, 330)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Cliente: {client_name}"))

        form = QFormLayout()
        self.phone_input = QLineEdit(phone or "")
        self.phone_input.setObjectName("whatsappPhoneInput")
        self.phone_input.setPlaceholderText("Ej.: +54 9 3743 123456")
        self.caption_input = QTextEdit(
            default_message
            or (
                f"Hola {client_name}. Le enviamos adjunto el resumen actualizado de su "
                "cuenta corriente con FEMAG. Ante cualquier consulta, quedamos a disposición."
            )
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


class WhatsAppTextDialog(QDialog):
    def __init__(
        self,
        *,
        recipient_name: str,
        phone: str,
        default_message: str | None = None,
        window_title: str = "Enviar mensaje por WhatsApp",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setObjectName("whatsappTextDialog")
        self.resize(560, 340)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Destinatario: {recipient_name}"))

        form = QFormLayout()
        self.phone_input = QLineEdit(phone or "")
        self.phone_input.setObjectName("whatsappTextPhoneInput")
        self.phone_input.setPlaceholderText("Ej.: +54 9 3743 123456")
        self.message_input = QTextEdit(
            default_message
            or (
                f"Hola {recipient_name}, le escribimos desde FEMAG. "
                "Ante cualquier consulta, quedamos a disposición."
            )
        )
        self.message_input.setObjectName("whatsappTextMessageInput")
        self.message_input.setMaximumHeight(120)
        form.addRow("Número", self.phone_input)
        form.addRow("Mensaje", self.message_input)
        root.addLayout(form)

        self.normalized_label = QLabel("")
        self.normalized_label.setObjectName("whatsappTextNormalizedPhone")
        root.addWidget(self.normalized_label)
        self.feedback = FormFeedback("whatsappTextFeedback")
        root.addWidget(self.feedback)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        send = QPushButton("Enviar mensaje")
        send.setObjectName("confirmWhatsAppTextSendButton")
        cancel.clicked.connect(self.reject)
        send.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(send)
        root.addLayout(actions)

        self.phone_input.textChanged.connect(self._preview_phone)
        self._preview_phone()

    def _preview_phone(self) -> None:
        classification = clasificar_telefono(self.phone_input.text())
        if classification.es_enviable:
            self.normalized_label.setText(
                f"Número final: +{classification.normalizado}"
            )
        elif classification.tiene_problema:
            self.normalized_label.setText(
                f"Teléfono {classification.etiqueta.lower()}: {classification.motivo}."
            )
        else:
            self.normalized_label.setText(
                f"Teléfono {classification.etiqueta.lower()}: "
                f"revisar antes de enviar ({classification.motivo})."
            )

    def _confirm(self) -> None:
        classification = clasificar_telefono(self.phone_input.text())
        if not classification.es_enviable:
            self.feedback.show_warning(
                f"El número no es un celular válido: {classification.motivo}.",
                focus_widget=self.phone_input,
            )
            return
        message = self.message_input.toPlainText().strip()
        if not message:
            self.feedback.show_warning(
                "Ingrese un mensaje para enviar.", focus_widget=self.message_input
            )
            return
        answer = QMessageBox.question(
            self,
            "Confirmar envío",
            f"¿Enviar este mensaje a +{classification.normalizado}?\n\n{message}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.accept()

    def phone(self) -> str:
        return self.phone_input.text().strip()

    def message(self) -> str:
        return self.message_input.toPlainText().strip()


class WhatsAppWorkerSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


class WhatsAppTextWorker(QRunnable):
    def __init__(
        self,
        *,
        envio_id: int,
        message: str,
        service: WhatsAppEnvioService | None = None,
    ):
        super().__init__()
        self.envio_id = envio_id
        self.message = message
        self.service = service or WhatsAppEnvioService()
        self.signals = WhatsAppWorkerSignals()

    def run(self) -> None:
        from app.models.whatsapp import WhatsAppEnvio

        try:
            envio = WhatsAppEnvio.get_by_id(self.envio_id)
            result = self.service.send_text(envio=envio, message=self.message)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


class WhatsAppSendWorker(QRunnable):
    def __init__(
        self,
        *,
        envio_id: int,
        pdf_path: Path,
        service: WhatsAppEnvioService | None = None,
    ):
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

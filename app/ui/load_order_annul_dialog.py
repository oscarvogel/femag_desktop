from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder


class LoadOrderAnnulDialog(QDialog):
    """Modal explícito para capturar el motivo obligatorio de anulación."""

    def __init__(self, order: LoadOrder, parent=None):
        super().__init__(parent)
        self.order = LoadOrder.get_by_id(order.id)
        self.setObjectName("loadOrderAnnulDialog")
        self.setWindowTitle(f"Anular orden OC-{self.order.order_number:06d}")
        self.setModal(True)
        self.resize(560, 300)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        title = QLabel(f"Anular orden OC-{self.order.order_number:06d}")
        title.setObjectName("loadOrderAnnulTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        help_text = QLabel(
            "Indique el motivo de la anulación. Este texto quedará registrado "
            "en el historial de auditoría de la orden."
        )
        help_text.setWordWrap(True)
        help_text.setProperty("uiRole", "muted")
        layout.addWidget(help_text)

        self.reason_input = QTextEdit()
        self.reason_input.setObjectName("loadOrderAnnulReasonInput")
        self.reason_input.setPlaceholderText(
            "Ej.: Error en transportista, cambio solicitado por el cliente, "
            "orden cargada por duplicado..."
        )
        self.reason_input.setMinimumHeight(120)
        layout.addWidget(self.reason_input, 1)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("loadOrderAnnulValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText("Cancelar")
        self.cancel_button.setObjectName("loadOrderAnnulCancelButton")
        self.annul_button = buttons.button(QDialogButtonBox.Ok)
        self.annul_button.setText("Anular orden")
        self.annul_button.setObjectName("loadOrderAnnulConfirmButton")
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)

        self.reason_input.setFocus()

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()

    def _validate_and_accept(self) -> None:
        if not self.reason():
            self.validation_label.setText("Debe indicar el motivo de la anulación.")
            self.reason_input.setFocus()
            return
        self.validation_label.clear()
        self.accept()

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)


class AuditReasonDialog(QDialog):
    """Modal reutilizable para acciones sensibles que requieren motivo."""

    def __init__(
        self,
        *,
        title: str,
        prompt: str,
        confirm_text: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("auditReasonDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(560, 300)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        heading = QLabel(title)
        heading.setObjectName("auditReasonTitle")
        heading.setProperty("uiRole", "sectionTitle")
        layout.addWidget(heading)

        help_text = QLabel(prompt)
        help_text.setWordWrap(True)
        help_text.setProperty("uiRole", "muted")
        layout.addWidget(help_text)

        self.reason_input = QTextEdit()
        self.reason_input.setObjectName("auditReasonInput")
        self.reason_input.setPlaceholderText("Indique el motivo de la operación...")
        self.reason_input.setMinimumHeight(120)
        layout.addWidget(self.reason_input, 1)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("auditReasonValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("auditReasonCancelButton")
        buttons.button(QDialogButtonBox.Ok).setText(confirm_text)
        buttons.button(QDialogButtonBox.Ok).setObjectName("auditReasonConfirmButton")
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)
        self.reason_input.setFocus()

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()

    def _validate_and_accept(self) -> None:
        if not self.reason():
            self.validation_label.setText("Debe indicar el motivo.")
            self.reason_input.setFocus()
            return
        self.validation_label.clear()
        self.accept()

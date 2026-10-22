"""Edición rápida del teléfono de un cliente (#705).

Es un diálogo chico, con un solo campo, para corregir un teléfono sin entrar al ABM
completo. Mientras se escribe, muestra **qué va a pasar con ese número**: si es un
celular (se puede mandar WhatsApp), si es una línea fija o un celular escrito sin el
"15" (ambiguo: se puede guardar, pero no se manda solo), o si no es un teléfono.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.client_service import ClientService
from app.services.whatsapp_phone_classifier import (
    ESTADO_CELULAR,
    ESTADO_POSIBLE,
    PhoneClassification,
    clasificar_telefono,
)
from app.ui.form_feedback import FormFeedback


_ESTILOS = {
    ESTADO_CELULAR: ("#166534", "#ecfdf3", "#4ade80"),
    ESTADO_POSIBLE: ("#92400e", "#fffbeb", "#f6c453"),
    "invalido": ("#991b1b", "#fef2f2", "#f87171"),
    "vacio": ("#374151", "#f3f4f6", "#d1d5db"),
}


class ClientPhoneEditDialog(QDialog):
    """Cambia el teléfono de un cliente y avisa cómo va a quedar."""

    def __init__(self, *, client, current_user: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Teléfono de {client.name}")
        self.setObjectName("clientPhoneEditDialog")
        self.resize(480, 260)
        self.setMinimumSize(420, 240)

        self.client = client
        self.current_user = current_user

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Cliente: {client.name}"))

        self.phone_input = QLineEdit(client.phone or "")
        self.phone_input.setObjectName("clientPhoneInput")
        self.phone_input.setPlaceholderText("Ej.: 011 15 53088679")
        root.addWidget(self.phone_input)

        self.classification_label = QLabel("")
        self.classification_label.setObjectName("clientPhoneClassificationLabel")
        self.classification_label.setWordWrap(True)
        root.addWidget(self.classification_label)

        self.proposal_btn = QPushButton("Usar el primer número")
        self.proposal_btn.setObjectName("clientPhoneProposalButton")
        self.proposal_btn.setVisible(False)
        root.addWidget(self.proposal_btn)

        self.feedback = FormFeedback("clientPhoneEditFeedback")
        root.addWidget(self.feedback)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        self.limpiar_btn = QPushButton("Borrar teléfono")
        self.limpiar_btn.setObjectName("clientPhoneClearButton")
        self.cancelar_btn = QPushButton("Cancelar")
        self.cancelar_btn.setObjectName("clientPhoneCancelButton")
        self.guardar_btn = QPushButton("Guardar")
        self.guardar_btn.setObjectName("clientPhoneSaveButton")
        acciones.addWidget(self.limpiar_btn)
        acciones.addWidget(self.cancelar_btn)
        acciones.addWidget(self.guardar_btn)
        root.addLayout(acciones)

        self.phone_input.textChanged.connect(self._reclasificar)
        self.proposal_btn.clicked.connect(self._usar_propuesta)
        self.limpiar_btn.clicked.connect(self._limpiar)
        self.cancelar_btn.clicked.connect(self.reject)
        self.guardar_btn.clicked.connect(self._guardar)
        self._reclasificar()

    # ------------------------------------------------------------------ UI

    def _reclasificar(self) -> None:
        clasificacion = clasificar_telefono(self.phone_input.text())
        self._pintar(clasificacion)
        self.proposal_btn.setVisible(bool(clasificacion.propuesta))

    def _pintar(self, clasificacion: PhoneClassification) -> None:
        color, fondo, borde = _ESTILOS.get(clasificacion.estado, _ESTILOS["vacio"])
        self.classification_label.setText(clasificacion.detalle)
        self.classification_label.setStyleSheet(
            f"QLabel {{"
            f"background-color: {fondo};"
            f"border: 1px solid {borde};"
            f"border-left: 4px solid {borde};"
            f"border-radius: 7px;"
            f"color: {color};"
            "font-size: 13px;"
            "font-weight: 600;"
            "padding: 9px 11px;"
            "}"
        )

    def _usar_propuesta(self) -> None:
        clasificacion = clasificar_telefono(self.phone_input.text())
        if clasificacion.propuesta:
            self.phone_input.setText(clasificacion.propuesta)

    def _limpiar(self) -> None:
        self.phone_input.setText("")

    def _guardar(self) -> None:
        telefono = self.phone_input.text().strip()
        try:
            ClientService(self.current_user).set_phone(self.client, telefono)
        except ValueError as exc:
            self.feedback.show_warning(str(exc), focus_widget=self.phone_input)
            return
        except Exception as exc:
            self.feedback.show_error(f"No se pudo guardar el teléfono: {exc}")
            return
        self.accept()

    def telefono(self) -> str:
        return self.phone_input.text().strip()

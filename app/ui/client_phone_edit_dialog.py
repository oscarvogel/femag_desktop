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
from app.services.whatsapp_phone_classifier import clasificar_telefono
from app.ui.form_feedback import FormFeedback
from app.ui.whatsapp_phone_edit_widgets import BotonPropuesta, ClasificacionLabel


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

        self.classification_label = ClasificacionLabel()
        self.classification_label.setObjectName("clientPhoneClassificationLabel")
        root.addWidget(self.classification_label)

        self.proposal_btn = BotonPropuesta("Usar el primer número")
        self.proposal_btn.setObjectName("clientPhoneProposalButton")
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
        self.classification_label.mostrar(clasificacion)
        self.proposal_btn.mostrar(clasificacion)

    def _usar_propuesta(self) -> None:
        clasificacion = clasificar_telefono(self.phone_input.text())
        propuesta = self.proposal_btn.aplicar(clasificacion)
        if propuesta:
            self.phone_input.setText(propuesta)

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

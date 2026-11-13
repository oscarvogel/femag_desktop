"""Edicion rapida del numero de WhatsApp de un cliente (#923).

Es un dialogo chico con un solo campo, como el del telefono, pero **estricto**:
aqui solo se guarda un celular sin ambiguedad, porque el campo tiene un solo
proposito. Un numero dudoso se muestra, pero no se puede guardar.

El dialogo no normaliza ni valida por su cuenta: eso lo hace
``WhatsAppContactService``, que ademas deja el numero guardado en formato
internacional y audita el cambio.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.whatsapp_contact_service import WhatsAppContactService
from app.services.whatsapp_phone_classifier import clasificar_telefono
from app.ui.form_feedback import FormFeedback
from app.ui.whatsapp_phone_edit_widgets import (
    BotonPropuesta,
    ClasificacionLabel,
    prefill_whatsapp,
)


class ClientWhatsappEditDialog(QDialog):
    """Cambia el numero de WhatsApp de un cliente y avisa como va a quedar."""

    def __init__(self, *, client, current_user: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"WhatsApp de {client.name}")
        self.setObjectName("clientWhatsappEditDialog")
        self.resize(480, 280)
        self.setMinimumSize(420, 260)

        self.client = client
        self.current_user = current_user

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Cliente: {client.name}"))

        self.whatsapp_input = QLineEdit(prefill_whatsapp(client.whatsapp_phone))
        self.whatsapp_input.setObjectName("clientWhatsappInput")
        self.whatsapp_input.setPlaceholderText("Ej.: 011 15 53088679")
        root.addWidget(self.whatsapp_input)

        self.classification_label = ClasificacionLabel()
        self.classification_label.setObjectName("clientWhatsappClassificationLabel")
        root.addWidget(self.classification_label)

        self.proposal_btn = BotonPropuesta()
        self.proposal_btn.setObjectName("clientWhatsappProposalButton")
        root.addWidget(self.proposal_btn)

        self.feedback = FormFeedback("clientWhatsappEditFeedback")
        root.addWidget(self.feedback)

        acciones = QHBoxLayout()
        acciones.addStretch(1)
        self.limpiar_btn = QPushButton("Borrar WhatsApp")
        self.limpiar_btn.setObjectName("clientWhatsappClearButton")
        self.cancelar_btn = QPushButton("Cancelar")
        self.cancelar_btn.setObjectName("clientWhatsappCancelButton")
        self.guardar_btn = QPushButton("Guardar")
        self.guardar_btn.setObjectName("clientWhatsappSaveButton")
        acciones.addWidget(self.limpiar_btn)
        acciones.addWidget(self.cancelar_btn)
        acciones.addWidget(self.guardar_btn)
        root.addLayout(acciones)

        self.whatsapp_input.textChanged.connect(self._reclasificar)
        self.proposal_btn.clicked.connect(self._usar_propuesta)
        self.limpiar_btn.clicked.connect(self._limpiar)
        self.cancelar_btn.clicked.connect(self.reject)
        self.guardar_btn.clicked.connect(self._guardar)
        self._reclasificar()

    def _reclasificar(self) -> None:
        clasificacion = clasificar_telefono(self.whatsapp_input.text())
        self.classification_label.mostrar(clasificacion)
        self.proposal_btn.mostrar(clasificacion)

    def _usar_propuesta(self) -> None:
        clasificacion = clasificar_telefono(self.whatsapp_input.text())
        propuesta = self.proposal_btn.aplicar(clasificacion)
        if propuesta:
            self.whatsapp_input.setText(propuesta)

    def _limpiar(self) -> None:
        self.whatsapp_input.setText("")

    def _guardar(self) -> None:
        numero = self.whatsapp_input.text().strip()
        try:
            WhatsAppContactService(self.current_user).set_client_whatsapp_phone(
                self.client, numero
            )
        except ValueError as exc:
            self.feedback.show_warning(str(exc), focus_widget=self.whatsapp_input)
            return
        except Exception as exc:
            self.feedback.show_error(f"No se pudo guardar el WhatsApp: {exc}")
            return
        self.accept()

    def whatsapp(self) -> str:
        return self.whatsapp_input.text().strip()

from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.services.client_manual_credit_service import (
    ClientManualCreditError,
    ClientManualCreditService,
)
from app.ui.combo_autocomplete import enable_combo_autocomplete


class ClientManualCreditDialog(QDialog):
    def __init__(
        self,
        *,
        current_user: str,
        service: ClientManualCreditService | None = None,
        preset_client: Client | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Registrar crédito manual")
        self.setModal(True)
        self.resize(480, 380)
        self.service = service or ClientManualCreditService(current_user=current_user)
        self._registered_credit: ClientAccountMovement | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Registre una bonificación, descuento, devolución o ajuste "
                "a favor del cliente."
            )
        )

        form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientManualCreditClientCombo")
        enable_combo_autocomplete(self.client_combo, placeholder="Buscar cliente...")
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        if preset_client is not None:
            index = self.client_combo.findData(preset_client.id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
        form.addRow("Cliente", self.client_combo)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setObjectName("clientManualCreditDateInput")
        self.date_input.setCalendarPopup(True)
        form.addRow("Fecha", self.date_input)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setObjectName("clientManualCreditAmountInput")
        self.amount_input.setRange(0.01, 99999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setSingleStep(100.0)
        self.amount_input.setPrefix("$ ")
        form.addRow("Importe", self.amount_input)

        self.description_input = QLineEdit()
        self.description_input.setObjectName("clientManualCreditDescriptionInput")
        self.description_input.setPlaceholderText(
            "Bonificación, descuento, devolución, ajuste..."
        )
        form.addRow("Concepto", self.description_input)

        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("clientManualCreditReferenceInput")
        self.reference_input.setPlaceholderText("Comprobante o referencia opcional")
        form.addRow("Referencia", self.reference_input)

        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("clientManualCreditObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones opcionales")
        form.addRow("Observaciones", self.observations_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName(
            "clientManualCreditSaveButton"
        )
        buttons.button(QDialogButtonBox.Cancel).setObjectName(
            "clientManualCreditCancelButton"
        )
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def registered_credit(self) -> ClientAccountMovement | None:
        return self._registered_credit

    def _on_accept(self) -> None:
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, "Crédito manual", "Debe seleccionar un cliente.")
            return
        try:
            movement = self.service.register_manual_credit(
                client=Client.get_by_id(client_id),
                amount=self.amount_input.value(),
                credit_date=self.date_input.date().toPyDate(),
                description=self.description_input.text(),
                reference=self.reference_input.text(),
                observations=self.observations_input.text(),
            )
        except ClientManualCreditError as exc:
            QMessageBox.warning(self, "Crédito manual", str(exc))
            return
        self._registered_credit = movement
        self.accept()

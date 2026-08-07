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
from app.services.client_manual_debit_service import (
    ClientManualDebitError,
    ClientManualDebitService,
)
from app.ui.combo_autocomplete import enable_combo_autocomplete


class ClientManualDebitDialog(QDialog):
    def __init__(
        self,
        *,
        current_user: str,
        service: ClientManualDebitService | None = None,
        preset_client: Client | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Registrar débito manual")
        self.setModal(True)
        self.resize(460, 330)
        self.service = service or ClientManualDebitService(current_user=current_user)
        self._registered_debit: ClientAccountMovement | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Registre un ajuste, interés o nota de débito en la cuenta del cliente.")
        )

        form = QFormLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("clientManualDebitClientCombo")
        enable_combo_autocomplete(self.client_combo, placeholder="Buscar cliente...")
        for client in Client.select().order_by(Client.name):
            self.client_combo.addItem(client.name, client.id)
        if preset_client is not None:
            index = self.client_combo.findData(preset_client.id)
            if index >= 0:
                self.client_combo.setCurrentIndex(index)
        form.addRow("Cliente", self.client_combo)

        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setObjectName("clientManualDebitDateInput")
        self.date_input.setCalendarPopup(True)
        form.addRow("Fecha", self.date_input)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setObjectName("clientManualDebitAmountInput")
        self.amount_input.setRange(0.0, 99999999.99)
        self.amount_input.setDecimals(2)
        self.amount_input.setSingleStep(100.0)
        self.amount_input.setPrefix("$ ")
        form.addRow("Monto", self.amount_input)

        self.description_input = QLineEdit()
        self.description_input.setObjectName("clientManualDebitDescriptionInput")
        self.description_input.setPlaceholderText("Interés, ajuste, nota de débito...")
        form.addRow("Descripción", self.description_input)

        self.reference_input = QLineEdit()
        self.reference_input.setObjectName("clientManualDebitReferenceInput")
        self.reference_input.setPlaceholderText("Comprobante o referencia opcional")
        form.addRow("Referencia", self.reference_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("clientManualDebitSaveButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("clientManualDebitCancelButton")
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def registered_debit(self) -> ClientAccountMovement | None:
        return self._registered_debit

    def _on_accept(self) -> None:
        client_id = self.client_combo.currentData()
        if client_id is None:
            QMessageBox.warning(self, "Débito manual", "Debe seleccionar un cliente.")
            return
        try:
            movement = self.service.register_manual_debit(
                client=Client.get_by_id(client_id),
                amount=self.amount_input.value(),
                debit_date=self.date_input.date().toPyDate(),
                description=self.description_input.text(),
                reference=self.reference_input.text(),
            )
        except ClientManualDebitError as exc:
            QMessageBox.warning(self, "Débito manual", str(exc))
            return
        self._registered_debit = movement
        self.accept()

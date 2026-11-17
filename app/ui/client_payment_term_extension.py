from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QSpinBox

from app.models.masters import Client
from app.services.client_service import ClientService


def install_client_payment_term_extension() -> None:
    """Extend the client editor with payment-term and credit-limit fields.

    La extension agrega sus filas al formulario que arma ``ClientEntryDialog``
    en vez de reimplementarlo: antes tenia una copia completa de ``_build``,
    ``_load_record`` y ``_save``, y cualquier campo nuevo del cliente (como el
    WhatsApp de #928) quedaba afuera del dialogo que se ve en runtime.
    """
    from app.ui import master_abm

    base_dialog = master_abm.ClientEntryDialog
    if getattr(base_dialog, "_payment_term_extension_installed", False):
        return

    class ClientEntryDialog(base_dialog):
        _payment_term_extension_installed = True

        def _build(self) -> None:
            super()._build()
            self.payment_term_input = QSpinBox()
            self.payment_term_input.setObjectName("clientPaymentTermDaysInput")
            self.payment_term_input.setRange(0, 3650)
            self.payment_term_input.setSuffix(" dias")
            self.payment_term_input.setSpecialValueText("Contado")
            self.credit_limit_input = QSpinBox()
            self.credit_limit_input.setObjectName("clientPendingDispatchLimitInput")
            self.credit_limit_input.setRange(0, 999)
            self.credit_limit_input.setSuffix(" despachos")
            self.credit_limit_input.setSpecialValueText("Sin limite")

            fila = self._form.rowCount()
            self._form.addWidget(QLabel("Plazo de pago"), fila, 0)
            self._form.addWidget(self.payment_term_input, fila, 1)
            self._form.addWidget(QLabel("Max. despachos pendientes"), fila + 1, 0)
            self._form.addWidget(self.credit_limit_input, fila + 1, 1)

        def _load_record(self) -> None:
            super()._load_record()
            if self.record_id is None:
                return
            client = Client.get_by_id(self.record_id)
            self.payment_term_input.setValue(int(client.dias_plazo_pago or 0))
            self.credit_limit_input.setValue(int(client.max_despachos_pendientes or 0))

        def _save_extra_fields(self, client) -> None:
            client.dias_plazo_pago = ClientService.validate_payment_term_days(
                self.payment_term_input.value()
            )
            client.max_despachos_pendientes = self.credit_limit_input.value() or None
            client.save(
                only=[
                    Client.dias_plazo_pago,
                    Client.max_despachos_pendientes,
                ]
            )

    master_abm.ClientEntryDialog = ClientEntryDialog

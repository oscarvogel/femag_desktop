from __future__ import annotations

from PyQt5.QtWidgets import QGridLayout, QLabel, QLineEdit, QSpinBox

from app.models.masters import Client
from app.services.client_service import ClientService


def install_client_payment_term_extension() -> None:
    """Extend the client editor with payment-term and credit-limit fields."""
    from app.ui import master_abm

    base_dialog = master_abm.ClientEntryDialog
    if getattr(base_dialog, "_payment_term_extension_installed", False):
        return

    class ClientEntryDialog(base_dialog):
        _payment_term_extension_installed = True

        def _build(self) -> None:
            layout = master_abm._entry_layout(self, "Cliente")
            form = QGridLayout()
            self.name_input = QLineEdit()
            self.name_input.setObjectName("clientNameInput")
            self.cuit_input = QLineEdit()
            self.cuit_input.setObjectName("clientCuitInput")
            self.iva_input = QLineEdit()
            self.iva_input.setObjectName("clientIvaInput")
            self.phone_input = QLineEdit()
            self.phone_input.setObjectName("clientPhoneInput")
            self.price_list_combo = master_abm._combo(
                "clientPriceListInput",
                master_abm._price_list_options(),
                include_empty=False,
            )
            self.payment_term_input = QSpinBox()
            self.payment_term_input.setObjectName("clientPaymentTermDaysInput")
            self.payment_term_input.setRange(0, 3650)
            self.payment_term_input.setSuffix(" días")
            self.payment_term_input.setSpecialValueText("Contado")
            self.credit_limit_input = QSpinBox()
            self.credit_limit_input.setObjectName("clientPendingDispatchLimitInput")
            self.credit_limit_input.setRange(0, 999)
            self.credit_limit_input.setSuffix(" despachos")
            self.credit_limit_input.setSpecialValueText("Sin límite")

            form.addWidget(QLabel("Nombre"), 0, 0)
            form.addWidget(self.name_input, 0, 1)
            form.addWidget(QLabel("CUIT"), 1, 0)
            form.addWidget(self.cuit_input, 1, 1)
            form.addWidget(QLabel("IVA"), 2, 0)
            form.addWidget(self.iva_input, 2, 1)
            form.addWidget(QLabel("Telefono"), 3, 0)
            form.addWidget(self.phone_input, 3, 1)
            form.addWidget(QLabel("Lista de precios"), 4, 0)
            form.addWidget(self.price_list_combo, 4, 1)
            form.addWidget(QLabel("Plazo de pago"), 5, 0)
            form.addWidget(self.payment_term_input, 5, 1)
            form.addWidget(QLabel("Máx. despachos pendientes"), 6, 0)
            form.addWidget(self.credit_limit_input, 6, 1)
            layout.addLayout(form)
            self.feedback = master_abm._entry_feedback(layout)
            master_abm._entry_footer(layout, self, "saveClientButton", self._save)

        def _load_record(self) -> None:
            if self.record_id is None:
                self.iva_input.setText("RI")
                self.payment_term_input.setValue(0)
                self.credit_limit_input.setValue(0)
                return
            client = Client.get_by_id(self.record_id)
            self.name_input.setText(client.name)
            self.cuit_input.setText(client.cuit)
            self.iva_input.setText(client.iva_condition)
            self.phone_input.setText(client.phone or "")
            master_abm._set_combo(self.price_list_combo, client.lista_precios)
            self.payment_term_input.setValue(int(client.dias_plazo_pago or 0))
            self.credit_limit_input.setValue(int(client.max_despachos_pendientes or 0))

        def _save(self) -> None:
            name = self.name_input.text().strip()
            cuit = self.cuit_input.text().strip()
            iva = self.iva_input.text().strip()
            if not name or not cuit or not iva:
                self.feedback.setText("Complete nombre, CUIT e IVA.")
                return
            try:
                payment_term_days = ClientService.validate_payment_term_days(
                    self.payment_term_input.value()
                )
                credit_limit = self.credit_limit_input.value() or None
                if self.record_id is None:
                    client = ClientService(self.current_user).create_client(
                        name,
                        cuit,
                        iva,
                        phone=self.phone_input.text().strip() or None,
                        lista_precios=int(self.price_list_combo.currentData() or 1),
                        dias_plazo_pago=payment_term_days,
                    )
                    client.max_despachos_pendientes = credit_limit
                    client.save()
                    self.saved_record = client
                else:
                    client = Client.get_by_id(self.record_id)
                    client.name = name
                    client.cuit = cuit
                    client.iva_condition = iva
                    client.phone = self.phone_input.text().strip() or None
                    client.lista_precios = int(self.price_list_combo.currentData() or 1)
                    client.dias_plazo_pago = payment_term_days
                    client.max_despachos_pendientes = credit_limit
                    client.save()
                    self.saved_record = client
                self.accept()
            except Exception as exc:
                self.feedback.setText(str(exc))

    master_abm.ClientEntryDialog = ClientEntryDialog
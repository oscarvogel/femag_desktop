from __future__ import annotations

from peewee import JOIN, InterfaceError, OperationalError
from PyQt5.QtCore import QEvent, QObject, QThreadPool, Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.budgets import Budget
from app.models.dgr import DgrLocality
from app.models.load_orders import LoadOrder
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    ClientEmail,
    Driver,
    Truck,
    client_address_type_label,
)
from app.services import ledger_query_service
from app.services.permission_service import PermissionService
from app.services.whatsapp_envio_service import WhatsAppEnvioService
from app.ui.whatsapp_send import WhatsAppTextDialog, WhatsAppTextWorker

DETAIL_MODELS = {
    "client": Client,
    "carrier": Carrier,
    "driver": Driver,
    "truck": Truck,
}
DETAIL_OBJECT_NAMES = {
    "client": "clientDetailDialog",
    "carrier": "carrierDetailDialog",
    "driver": "driverDetailDialog",
    "truck": "truckDetailDialog",
}
DETAIL_TITLES = {
    "client": "Ficha de cliente",
    "carrier": "Ficha de transportista",
    "driver": "Ficha de chofer",
    "truck": "Ficha de camión",
}
WHATSAPP_DOC_TYPES = {
    "client": "mensaje_ficha_cliente",
    "carrier": "mensaje_ficha_transportista",
    "driver": "mensaje_ficha_chofer",
}
WHATSAPP_PERMISSION_TITLES = {
    "client": "Clientes",
    "carrier": "Transportistas",
    "driver": "Choferes",
}
WHATSAPP_STATUS_LABELS = {
    "queued": "encolado",
    "processing": "procesando",
    "accepted": "aceptado por WhatsApp",
    "delivered": "entregado",
    "read": "leído",
    "failed": "fallido",
}


def _text(value: object, empty: str = "Sin asignar") -> str:
    if value is None:
        return empty
    text = str(value).strip()
    return text or empty


def _state(active: object) -> str:
    return "Activo" if active else "Inactivo"


def _availability(available: object) -> str:
    return "Disponible" if available else "No disponible"


class _DetailActivationFilter(QObject):
    def __init__(self, table: QTableWidget, callback):
        super().__init__(table)
        self.table = table
        self.callback = callback

    def eventFilter(self, watched, event):
        if (
            watched is self.table
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and self.table.currentRow() >= 0
        ):
            self.callback()
            return True
        return False


class MasterDetailDialog(QDialog):
    detail_kind = None

    def __init__(
        self,
        *,
        record_id: int,
        current_user: str | None = None,
        parent=None,
        kind: str | None = None,
        user=None,
        can_edit_callback=None,
        edit_callback=None,
        view_ledger_callback=None,
        print_envelope_callback=None,
    ):
        super().__init__(parent)
        self.record_id = record_id
        self.current_user = current_user
        self.user = user
        self.can_edit_callback = can_edit_callback
        self.edit_callback = edit_callback
        self.view_ledger_callback = view_ledger_callback
        self.print_envelope_callback = print_envelope_callback
        self.kind = kind or self.detail_kind or "client"
        self.record = None
        self._history: list[tuple[str, int, int, str | None, int | None]] = []
        self._whatsapp_workers: set = set()
        self.navigated_away = False
        self.resize(940, 580)
        self.setSizeGripEnabled(True)
        self._root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("masterDetailTabs")
        self._root.addWidget(self.tabs, 1)
        self.whatsapp_status_label = QLabel("")
        self.whatsapp_status_label.setObjectName("masterDetailWhatsAppStatus")
        self.whatsapp_status_label.setWordWrap(True)
        self._root.addWidget(self.whatsapp_status_label)
        footer = QHBoxLayout()
        self.back_button = QPushButton("Volver")
        self.back_button.setObjectName("backMasterDetailButton")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self.go_back)
        footer.addWidget(self.back_button)
        self.edit_button = QPushButton("Editar")
        self.edit_button.setObjectName("editMasterDetailButton")
        self.edit_button.clicked.connect(self._edit_current)
        footer.addWidget(self.edit_button)
        footer.addStretch(1)
        self.close_button = QPushButton("Cerrar")
        self.close_button.setObjectName("closeMasterDetailButton")
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        self._root.addLayout(footer)
        self._render_current()

    def load_record(self):
        model = DETAIL_MODELS.get(self.kind)
        if model is None:
            return None
        return model.get_or_none(model.id == self.record_id)

    def _render_current(self, tab_index: int = 0) -> None:
        self.record = self.load_record()
        self.setObjectName(DETAIL_OBJECT_NAMES.get(self.kind, "masterDetailDialog"))
        self.setWindowTitle(DETAIL_TITLES.get(self.kind, "Ficha"))
        self.whatsapp_status_label.setText("")
        can_edit = bool(
            self.can_edit_callback is not None and self.can_edit_callback(self.kind)
        )
        self.edit_button.setEnabled(can_edit)
        self.edit_button.setToolTip(
            "" if can_edit else "El perfil actual no permite modificar este maestro."
        )
        old_tabs = self.tabs
        new_tabs = QTabWidget()
        new_tabs.setObjectName("masterDetailTabs")
        self._root.replaceWidget(old_tabs, new_tabs)
        old_tabs.setParent(None)
        old_tabs.deleteLater()
        self.tabs = new_tabs
        self.build_tabs()
        if self.tabs.count():
            self.tabs.setCurrentIndex(
                min(max(tab_index, 0), self.tabs.count() - 1)
            )
        self.back_button.setEnabled(bool(self._history))

    def build_tabs(self) -> None:
        builders = {
            "client": self._build_client_tabs,
            "carrier": self._build_carrier_tabs,
            "driver": self._build_driver_tabs,
            "truck": self._build_truck_tabs,
        }
        builder = builders.get(self.kind)
        if builder is not None:
            builder()

    def navigate_to(
        self,
        kind: str,
        record_id: int | None,
        *,
        focus_object_name: str | None = None,
        focus_row: int | None = None,
    ) -> None:
        if kind not in DETAIL_MODELS or record_id is None:
            return
        if kind == self.kind and record_id == self.record_id:
            return
        self._history.append(
            (
                self.kind,
                self.record_id,
                self.tabs.currentIndex(),
                focus_object_name,
                focus_row,
            )
        )
        self.kind = kind
        self.record_id = record_id
        self._render_current()

    def go_back(self) -> None:
        if not self._history:
            return
        kind, record_id, tab_index, focus_object_name, focus_row = self._history.pop()
        self.kind = kind
        self.record_id = record_id
        self._render_current(tab_index)
        self._restore_focus(focus_object_name, focus_row)

    def _restore_focus(
        self, object_name: str | None, row: int | None = None
    ) -> None:
        if object_name is None:
            return
        widget = self.findChild(QWidget, object_name)
        if widget is None:
            return
        if isinstance(widget, QTableWidget) and row is not None:
            if 0 <= row < widget.rowCount():
                widget.setCurrentCell(row, 0)
        widget.setFocus()

    def _has_permission(self, section: str, action: str, title: str) -> bool:
        if self.user is None or not getattr(self.user, "active", False):
            return False
        try:
            return PermissionService().has_permission(
                self.user, section, action, title
            )
        except (InterfaceError, OperationalError):
            return False

    def _can_view_ledger(self) -> bool:
        return self._has_permission(
            "Cuenta corriente", "ver", "Movimientos"
        ) or self._has_permission("Cuenta corriente", "ver", "Clientes con saldo")

    def _can_print_envelope(self) -> bool:
        return self._has_permission(
            "Maestros", "imprimir", "Clientes"
        ) or self._has_permission("Maestros", "reimprimir", "Clientes")

    def _can_send_whatsapp(self, kind: str) -> bool:
        title = WHATSAPP_PERMISSION_TITLES.get(kind)
        if title is None:
            return False
        return self._has_permission("Maestros", "ver", title)

    def _edit_current(self) -> None:
        if self.edit_callback is None:
            return
        if not self.can_edit_callback or not self.can_edit_callback(self.kind):
            return
        if self.edit_callback(self.kind, self.record_id):
            self._render_current(self.tabs.currentIndex())

    def _open_ledger(self) -> None:
        client = self.record
        if client is None or self.view_ledger_callback is None:
            return
        self.navigated_away = True
        self.accept()
        QTimer.singleShot(0, lambda: self.view_ledger_callback(client))

    def _whatsapp_button(
        self,
        *,
        kind: str,
        recipient_name: str,
        phone: str | None,
        object_name: str,
    ) -> QPushButton:
        button = QPushButton("WhatsApp")
        button.setObjectName(object_name)
        if not self._can_send_whatsapp(kind):
            button.setEnabled(False)
            button.setToolTip("El perfil actual no permite enviar mensajes.")
        elif not (phone or "").strip():
            button.setEnabled(False)
            button.setToolTip("El registro no tiene teléfono guardado.")
        else:
            button.clicked.connect(
                lambda _checked=False: self._open_whatsapp(
                    kind=kind,
                    recipient_name=recipient_name,
                    phone=phone or "",
                )
            )
        return button

    def _open_whatsapp(self, *, kind: str, recipient_name: str, phone: str) -> None:
        document_type = WHATSAPP_DOC_TYPES.get(kind)
        if document_type is None:
            return
        dialog = WhatsAppTextDialog(
            recipient_name=recipient_name,
            phone=phone,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        message = dialog.message()
        try:
            service = WhatsAppEnvioService()
            envio = service.create_text_attempt(
                tipo_documento=document_type,
                documento_id=str(self.record_id),
                destinatario=dialog.phone(),
                message=message,
                usuario=self.user,
            )
        except Exception as exc:  # noqa: BLE001 - se informa al operador
            QMessageBox.warning(self, "WhatsApp", str(exc))
            return
        self.whatsapp_status_label.setText("WhatsApp: enviando...")
        worker = WhatsAppTextWorker(
            envio_id=envio.id,
            message=message,
            service=service,
        )
        self._whatsapp_workers.add(worker)
        worker.signals.succeeded.connect(self._whatsapp_succeeded)
        worker.signals.failed.connect(self._whatsapp_failed)
        worker.signals.finished.connect(
            lambda: self._whatsapp_workers.discard(worker)
        )
        QThreadPool.globalInstance().start(worker)

    def _whatsapp_succeeded(self, envio) -> None:
        status = WHATSAPP_STATUS_LABELS.get(envio.estado, envio.estado)
        message_id = f" (ID {envio.message_id})" if envio.message_id else ""
        self.whatsapp_status_label.setText(f"WhatsApp: {status}{message_id}")

    def _whatsapp_failed(self, message: str) -> None:
        self.whatsapp_status_label.setText(f"WhatsApp: error - {message}")
        QMessageBox.warning(
            self, "WhatsApp", f"No se pudo completar el envío: {message}"
        )

    def _print_selected_envelope(self) -> None:
        table = self.findChild(QTableWidget, "clientDetailBudgetsTable")
        if table is None or self.print_envelope_callback is None:
            return
        item = table.item(table.currentRow(), 0)
        if item is None:
            QMessageBox.information(
                self, "Sobre", "Seleccione un presupuesto para imprimir el sobre."
            )
            return
        budget = Budget.get_or_none(Budget.id == item.data(Qt.UserRole))
        if budget is None:
            QMessageBox.warning(self, "Sobre", "El presupuesto seleccionado no existe.")
            return
        try:
            self.print_envelope_callback(budget)
        except Exception as exc:  # noqa: BLE001 - se informa al operador
            QMessageBox.warning(
                self, "Sobre", f"No se pudo generar el sobre: {exc}"
            )

    def add_tab(self, title: str, widget: QWidget) -> None:
        self.tabs.addTab(widget, title)

    def navigation_button(
        self,
        *,
        text: str,
        object_name: str,
        kind: str,
        record_id: int | None,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        if record_id is None:
            button.setEnabled(False)
            button.setToolTip("Sin registro relacionado.")
        else:
            button.clicked.connect(
                lambda _checked=False, target_kind=kind, target_id=record_id: self.navigate_to(
                    target_kind,
                    target_id,
                    focus_object_name=object_name,
                )
            )
        return button

    def form_tab(
        self,
        fields: list[tuple[str, object, str]],
        *,
        actions: list[QWidget] | None = None,
    ) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for row, (label_text, value, object_name) in enumerate(fields):
            label = QLabel(label_text)
            label.setObjectName(f"{object_name}Label")
            value_label = QLabel(_text(value))
            value_label.setObjectName(object_name)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(label, row, 0)
            grid.addWidget(value_label, row, 1)
        grid.setRowStretch(len(fields), 1)
        outer.addLayout(grid)
        if actions:
            action_row = QHBoxLayout()
            for action in actions:
                action_row.addWidget(action)
            action_row.addStretch(1)
            outer.addLayout(action_row)
        return widget

    def table_tab(
        self,
        *,
        headers: list[str],
        rows: list[list[object]],
        object_name: str,
        record_kind: str | None = None,
        record_ids: list[int] | None = None,
        actions: list[QWidget] | None = None,
    ) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        if actions:
            action_row = QHBoxLayout()
            for action in actions:
                action_row.addWidget(action)
            action_row.addStretch(1)
            layout.addLayout(action_row)
        table = QTableWidget(len(rows), len(headers))
        table.setObjectName(object_name)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row_index, row_values in enumerate(rows):
            for column, value in enumerate(row_values):
                table.setItem(row_index, column, QTableWidgetItem(_text(value, "")))
            if record_ids is not None and row_index < len(record_ids):
                table.item(row_index, 0).setData(Qt.UserRole, record_ids[row_index])
        if rows:
            table.setCurrentCell(0, 0)
        layout.addWidget(table, 1)
        if not rows:
            layout.addWidget(QLabel("Sin registros para mostrar."))
        if record_kind is not None and record_ids:
            self._bind_table_navigation(table, record_kind)
        return widget

    def _bind_table_navigation(self, table: QTableWidget, record_kind: str) -> None:
        def activate() -> None:
            item = table.item(table.currentRow(), 0)
            if item is None:
                return
            self.navigate_to(
                record_kind,
                item.data(Qt.UserRole),
                focus_object_name=table.objectName(),
                focus_row=table.currentRow(),
            )

        table.itemDoubleClicked.connect(lambda *_args: activate())
        activation_filter = _DetailActivationFilter(table, activate)
        table.installEventFilter(activation_filter)
        table._master_detail_activation_filter = activation_filter

    def _build_client_tabs(self) -> None:
        if self.record is None:
            self.add_tab(
                "Datos", self.form_tab([("ID", self.record_id, "clientDetailIdValue")])
            )
            return
        client = self.record
        self.setWindowTitle(
            f"Ficha de cliente - {client.name}" + ("" if client.active else " (inactivo)")
        )
        salesperson = client.salesperson.name if client.salesperson_id is not None else None
        fields = [
            ("ID", client.id, "clientDetailIdValue"),
            ("Razón social", client.name, "clientDetailNameValue"),
            ("CUIT", client.cuit or "Sin CUIT", "clientDetailCuitValue"),
            ("Condición IVA", client.iva_condition, "clientDetailIvaValue"),
            ("Teléfono", client.phone or "Sin teléfono", "clientDetailPhoneValue"),
            ("Email", client.email or "Sin email", "clientDetailEmailValue"),
            ("Contacto", client.contact or "Sin contacto", "clientDetailContactValue"),
            ("Vendedor", salesperson, "clientDetailSalespersonValue"),
            (
                "Lista de precios",
                f"Lista {client.lista_precios}",
                "clientDetailPriceListValue",
            ),
            (
                "Descuento",
                f"{client.descuento_porcentaje:g}%",
                "clientDetailDiscountValue",
            ),
            (
                "Días de pago",
                f"{client.dias_plazo_pago} días",
                "clientDetailPaymentDaysValue",
            ),
            (
                "Máx. despachos pendientes",
                (
                    "Sin límite"
                    if client.max_despachos_pendientes is None
                    else client.max_despachos_pendientes
                ),
                "clientDetailMaxPendingValue",
            ),
            ("Estado", _state(client.active), "clientDetailActiveValue"),
        ]
        actions = [
            self._whatsapp_button(
                kind="client",
                recipient_name=client.name,
                phone=client.phone,
                object_name="clientDetailWhatsAppButton",
            )
        ]
        if self._can_view_ledger():
            balance = ledger_query_service.client_balance(client)
            fields.append(
                ("Saldo actual", f"${balance:,.2f}", "clientDetailBalanceValue")
            )
            open_ledger_button = QPushButton("Ver cuenta corriente")
            open_ledger_button.setObjectName("clientDetailOpenLedgerButton")
            open_ledger_button.setEnabled(self.view_ledger_callback is not None)
            if self.view_ledger_callback is None:
                open_ledger_button.setToolTip(
                    "La pantalla de cuenta corriente no está disponible."
                )
            else:
                open_ledger_button.clicked.connect(self._open_ledger)
            actions.insert(0, open_ledger_button)
        self.add_tab(
            "Datos",
            self.form_tab(fields, actions=actions),
        )

        addresses = list(
            ClientAddress.select()
            .where(ClientAddress.client == client.id)
            .order_by(ClientAddress.address_type, ClientAddress.address)
        )
        locality_ids = {address.locality_id for address in addresses if address.locality_id}
        locality_names = (
            {
                locality.id: locality.name
                for locality in DgrLocality.select().where(DgrLocality.id.in_(locality_ids))
            }
            if locality_ids
            else {}
        )
        address_rows = [
            [
                client_address_type_label(address.address_type),
                "Sí" if address.is_primary else "",
                address.address,
                address.city,
                address.province,
                locality_names.get(address.locality_id),
                address.observations,
                _state(address.active),
            ]
            for address in addresses
        ]
        self.add_tab(
            f"Domicilios ({len(addresses)})",
            self.table_tab(
                headers=[
                    "Tipo",
                    "Principal",
                    "Dirección",
                    "Ciudad",
                    "Provincia",
                    "Localidad DGR",
                    "Observaciones",
                    "Estado",
                ],
                rows=address_rows,
                object_name="clientDetailAddressesTable",
            ),
        )

        emails = list(
            ClientEmail.select()
            .where(ClientEmail.client == client.id)
            .order_by(ClientEmail.is_primary.desc(), ClientEmail.id)
        )
        email_rows = [
            [
                email.email,
                email.label,
                "Sí" if email.is_primary else "",
                _state(email.active),
                email.observations,
            ]
            for email in emails
        ]
        self.add_tab(
            f"Emails ({len(emails)})",
            self.table_tab(
                headers=["Email", "Etiqueta", "Principal", "Estado", "Observaciones"],
                rows=email_rows,
                object_name="clientDetailEmailsTable",
            ),
        )
        self._add_client_budgets_tab(client)

    def _add_client_budgets_tab(self, client: Client) -> None:
        budgets = list(
            Budget.select(Budget, LoadOrder)
            .join(
                LoadOrder,
                JOIN.LEFT_OUTER,
                on=(Budget.load_order == LoadOrder.id),
            )
            .where(
                Budget.client == client.id,
                Budget.status == Budget.STATUS_ACTIVE,
            )
            .order_by(Budget.issue_date.desc(), Budget.budget_number.desc())
        )
        rows = [
            [
                budget.display_number,
                (
                    "Orden de carga"
                    if budget.origin == Budget.ORIGIN_LOAD_ORDER
                    else "Manual"
                ),
                budget.load_order_reference or "-",
                budget.issue_date.strftime("%d/%m/%Y") if budget.issue_date else "",
                f"${budget.total_amount:,.2f}",
                budget.timing_label,
            ]
            for budget in budgets
        ]
        widget = self.table_tab(
            headers=[
                "Presupuesto",
                "Origen",
                "Orden",
                "Fecha",
                "Total",
                "Momento",
            ],
            rows=rows,
            object_name="clientDetailBudgetsTable",
            record_ids=[budget.id for budget in budgets],
        )
        print_button = QPushButton("Imprimir sobre seleccionado")
        print_button.setObjectName("clientDetailPrintEnvelopeButton")
        can_print = self._can_print_envelope()
        print_button.setEnabled(
            bool(budgets) and can_print and self.print_envelope_callback is not None
        )
        if not can_print:
            print_button.setToolTip(
                "El perfil actual no permite imprimir sobres."
            )
        elif self.print_envelope_callback is None:
            print_button.setToolTip("La impresión de sobres no está disponible.")
        elif not budgets:
            print_button.setToolTip(
                "El cliente no tiene presupuestos activos para generar un sobre."
            )
        else:
            print_button.clicked.connect(self._print_selected_envelope)
        layout = widget.layout()
        action_row = QHBoxLayout()
        action_row.addWidget(print_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        self.add_tab(f"Presupuestos ({len(budgets)})", widget)

    def _build_carrier_tabs(self) -> None:
        if self.record is None:
            self.add_tab(
                "Datos", self.form_tab([("ID", self.record_id, "carrierDetailIdValue")])
            )
            return
        carrier = self.record
        self.setWindowTitle(
            f"Ficha de transportista - {carrier.name}"
            + ("" if carrier.active else " (inactivo)")
        )
        locality = (
            DgrLocality.get_or_none(DgrLocality.id == carrier.locality_id)
            if carrier.locality_id is not None
            else None
        )
        self.add_tab(
            "Datos",
            self.form_tab(
                [
                    ("ID", carrier.id, "carrierDetailIdValue"),
                    ("Nombre", carrier.name, "carrierDetailNameValue"),
                    ("CUIT", carrier.cuit or "Sin CUIT", "carrierDetailCuitValue"),
                    ("Teléfono", carrier.phone or "Sin teléfono", "carrierDetailPhoneValue"),
                    ("Código", carrier.codigo or "Sin código", "carrierDetailCodeValue"),
                    ("Tipo", carrier.tipo or "Sin tipo", "carrierDetailTypeValue"),
                    ("Domicilio", carrier.address or "Sin domicilio", "carrierDetailAddressValue"),
                    (
                        "Localidad DGR",
                        locality.name if locality is not None else None,
                        "carrierDetailLocalityValue",
                    ),
                    ("Estado", _state(carrier.active), "carrierDetailActiveValue"),
                ],
                actions=[
                    self._whatsapp_button(
                        kind="carrier",
                        recipient_name=carrier.name,
                        phone=carrier.phone,
                        object_name="carrierDetailWhatsAppButton",
                    )
                ],
            ),
        )

        drivers = list(
            Driver.select()
            .where(Driver.carrier == carrier.id)
            .order_by(Driver.name)
        )
        self.add_tab(
            f"Choferes ({len(drivers)})",
            self.table_tab(
                headers=["Nombre", "Documento", "Teléfono", "Estado", "Disponibilidad"],
                rows=[
                    [
                        driver.name,
                        driver.document or "Sin documento",
                        driver.phone or "Sin teléfono",
                        _state(driver.active),
                        _availability(driver.available),
                    ]
                    for driver in drivers
                ],
                object_name="carrierDetailDriversTable",
                record_kind="driver",
                record_ids=[driver.id for driver in drivers],
            ),
        )

        trucks = list(
            Truck.select()
            .where(Truck.carrier == carrier.id)
            .order_by(Truck.domain)
        )
        self.add_tab(
            f"Camiones ({len(trucks)})",
            self.table_tab(
                headers=["Patente", "Acoplado", "Tipo de chasis", "Carga máxima", "Estado"],
                rows=[
                    [
                        truck.domain,
                        truck.trailer_domain or "Sin acoplado",
                        truck.chassis_type or "Sin tipo",
                        (
                            f"{truck.max_load_kg:.3f} kg"
                            if truck.max_load_kg is not None
                            else "Sin dato"
                        ),
                        _state(truck.active),
                    ]
                    for truck in trucks
                ],
                object_name="carrierDetailTrucksTable",
                record_kind="truck",
                record_ids=[truck.id for truck in trucks],
            ),
        )

    def _build_driver_tabs(self) -> None:
        if self.record is None:
            self.add_tab(
                "Datos", self.form_tab([("ID", self.record_id, "driverDetailIdValue")])
            )
            return
        driver = self.record
        self.setWindowTitle(
            f"Ficha de chofer - {driver.name}" + ("" if driver.active else " (inactivo)")
        )
        locality = (
            DgrLocality.get_or_none(DgrLocality.id == driver.locality_id)
            if driver.locality_id is not None
            else None
        )
        carrier = (
            Carrier.get_or_none(Carrier.id == driver.carrier_id)
            if driver.carrier_id is not None
            else None
        )
        truck = (
            Truck.get_or_none(Truck.id == driver.usual_truck_id)
            if driver.usual_truck_id is not None
            else None
        )
        self.add_tab(
            "Datos",
            self.form_tab(
                [
                    ("ID", driver.id, "driverDetailIdValue"),
                    ("Nombre", driver.name, "driverDetailNameValue"),
                    ("CUIT", driver.cuit or "Sin CUIT", "driverDetailCuitValue"),
                    (
                        "Documento",
                        driver.document or "Sin documento",
                        "driverDetailDocumentValue",
                    ),
                    ("Teléfono", driver.phone or "Sin teléfono", "driverDetailPhoneValue"),
                    ("Domicilio", driver.address or "Sin domicilio", "driverDetailAddressValue"),
                    (
                        "Localidad DGR",
                        locality.name if locality is not None else None,
                        "driverDetailLocalityValue",
                    ),
                    ("Estado", _state(driver.active), "driverDetailActiveValue"),
                    (
                        "Disponibilidad",
                        _availability(driver.available),
                        "driverDetailAvailableValue",
                    ),
                ],
                actions=[
                    self._whatsapp_button(
                        kind="driver",
                        recipient_name=driver.name,
                        phone=driver.phone,
                        object_name="driverDetailWhatsAppButton",
                    )
                ],
            ),
        )
        self.add_tab(
            "Relaciones",
            self.form_tab(
                [
                    (
                        "Transportista",
                        carrier.name if carrier is not None else None,
                        "driverDetailCarrierValue",
                    ),
                    (
                        "Camión habitual",
                        truck.domain if truck is not None else None,
                        "driverDetailTruckValue",
                    ),
                    (
                        "Acoplado habitual",
                        (
                            truck.trailer_domain or "Sin acoplado"
                            if truck is not None
                            else None
                        ),
                        "driverDetailTrailerValue",
                    ),
                ],
                actions=[
                    self.navigation_button(
                        text="Ver transportista",
                        object_name="driverDetailOpenCarrierButton",
                        kind="carrier",
                        record_id=driver.carrier_id,
                    ),
                    self.navigation_button(
                        text="Ver camión habitual",
                        object_name="driverDetailOpenTruckButton",
                        kind="truck",
                        record_id=driver.usual_truck_id,
                    ),
                ],
            ),
        )

    def _build_truck_tabs(self) -> None:
        if self.record is None:
            self.add_tab(
                "Datos", self.form_tab([("ID", self.record_id, "truckDetailIdValue")])
            )
            return
        truck = self.record
        self.setWindowTitle(
            f"Ficha de camión - {truck.domain}" + ("" if truck.active else " (inactivo)")
        )
        carrier = (
            Carrier.get_or_none(Carrier.id == truck.carrier_id)
            if truck.carrier_id is not None
            else None
        )
        self.add_tab(
            "Datos",
            self.form_tab(
                [
                    ("ID", truck.id, "truckDetailIdValue"),
                    ("Dominio", truck.domain, "truckDetailDomainValue"),
                    (
                        "Acoplado",
                        truck.trailer_domain or "Sin acoplado",
                        "truckDetailTrailerValue",
                    ),
                    (
                        "Transportista",
                        carrier.name if carrier is not None else None,
                        "truckDetailCarrierValue",
                    ),
                    (
                        "Tipo de chasis",
                        truck.chassis_type or "Sin tipo",
                        "truckDetailChassisValue",
                    ),
                    (
                        "Tipo de acoplado",
                        truck.trailer_type or "Sin tipo",
                        "truckDetailTrailerTypeValue",
                    ),
                    (
                        "Carga máxima",
                        (
                            f"{truck.max_load_kg:.3f} kg"
                            if truck.max_load_kg is not None
                            else "Sin dato"
                        ),
                        "truckDetailMaxLoadValue",
                    ),
                    ("Estado", _state(truck.active), "truckDetailActiveValue"),
                ]
            ),
        )
        drivers = list(
            Driver.select()
            .where(Driver.usual_truck == truck.id)
            .order_by(Driver.name)
        )
        self.add_tab(
            f"Choferes habituales ({len(drivers)})",
            self.table_tab(
                headers=["Nombre", "Documento", "Teléfono", "Estado", "Disponibilidad"],
                rows=[
                    [
                        driver.name,
                        driver.document or "Sin documento",
                        driver.phone or "Sin teléfono",
                        _state(driver.active),
                        _availability(driver.available),
                    ]
                    for driver in drivers
                ],
                object_name="truckDetailDriversTable",
                record_kind="driver",
                record_ids=[driver.id for driver in drivers],
                actions=[
                    self.navigation_button(
                        text="Ver transportista",
                        object_name="truckDetailOpenCarrierButton",
                        kind="carrier",
                        record_id=truck.carrier_id,
                    )
                ],
            ),
        )


class ClientDetailDialog(MasterDetailDialog):
    detail_kind = "client"


class CarrierDetailDialog(MasterDetailDialog):
    detail_kind = "carrier"


class DriverDetailDialog(MasterDetailDialog):
    detail_kind = "driver"


class TruckDetailDialog(MasterDetailDialog):
    detail_kind = "truck"

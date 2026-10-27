from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from PyQt5.QtCore import QDate, QUrl, Qt
from PyQt5.QtGui import QDesktopServices, QDoubleValidator
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance, RemittanceSeries
from app.services.f150_batch_service import F150BatchService
from app.services.money import ZERO_MONEY, money_sum, quantize_money
from app.services.pricing import price_for_client_list
from app.services.remittance_print_service import RemittancePrintService
from app.services.remittance_service import RemittanceSeriesService, RemittanceService
from app.ui.audit_reason_dialog import AuditReasonDialog
from app.ui.combo_autocomplete import (
    SEARCH_COLUMNS_ROLE,
    SearchableComboBox,
    combo_current_data,
    commit_combo_text,
)
from app.ui.remittance_history_dialog import RemittanceHistoryDialog


REMITTANCE_PRINTS_DIR = Path("outputs") / "remittances"
F150_OUTPUT_DIR = Path("outputs") / "f150"

DRIVER_HINT = (
    "Elegi el chofer: el transportista, el camion y el acoplado se completan solos. "
    "Si escribis la patente del acoplado a mano, esa manda. F2 abre la busqueda."
)


class RemittanceDialog(QDialog):
    def __init__(self, *, current_user: str, remittance: Remittance | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.remittance = remittance
        self.setWindowTitle("Remito")
        self.resize(1080, 720)
        self.setMinimumSize(920, 650)
        root = QVBoxLayout(self)
        header_group = QGroupBox("Cabecera del remito")
        header_group.setObjectName("remittanceHeaderGroup")
        form = QGridLayout(header_group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.client_combo = SearchableComboBox(
            placeholder="Buscar cliente...",
            search_headers=("Cliente", "CUIT"),
        )
        self.address_combo = SearchableComboBox(
            placeholder="Buscar domicilio...",
            search_headers=("Domicilio", "Ciudad", "Provincia"),
        )
        self.carrier_combo = SearchableComboBox(
            placeholder="Buscar transportista...",
            search_headers=("Transportista", "CUIT"),
        )
        self.carrier_combo.setObjectName("remittanceCarrierInput")
        self.truck_combo = SearchableComboBox(
            placeholder="Buscar camión...",
            search_headers=("Camión", "Acoplado", "Transportista"),
        )
        self.truck_combo.setObjectName("remittanceTruckInput")
        self.driver_combo = SearchableComboBox(
            placeholder="Buscar chofer...",
            hint=DRIVER_HINT,
            search_headers=("Chofer", "Documento", "Transportista"),
        )
        self.driver_combo.setObjectName("remittanceDriverInput")
        # Numero de remito manual: no se usa talonario correlativo. Se acepta
        # cualquier numero libre y se valida que no este usado (solo al emitir
        # es obligatorio).
        self.point_input = QLineEdit()
        self.point_input.setObjectName("remittancePointInput")
        self.point_input.setPlaceholderText("0001")
        self.point_input.setMaxLength(4)
        self.point_input.setMinimumWidth(60)
        self.point_input.setMaximumWidth(80)
        self.number_input = QLineEdit()
        self.number_input.setObjectName("remittanceNumberInput")
        self.number_input.setPlaceholderText("N° aleatorio del formulario")
        self.number_input.setMaxLength(9)
        number_box = QHBoxLayout()
        number_box.setContentsMargins(0, 0, 0, 0)
        number_box.setSpacing(4)
        number_box.addWidget(self.point_input)
        number_box.addWidget(QLabel("-"))
        number_box.addWidget(self.number_input, 1)
        self.trailer_input = QLineEdit()
        self.trailer_input.setObjectName("remittanceTrailerInput")
        self.trailer_input.setPlaceholderText("Patente del acoplado (opcional)")
        self.trailer_input.setMaxLength(10)
        self.reference_input = QLineEdit()
        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("remittanceObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones opcionales")
        form.addWidget(QLabel("Fecha"), 0, 0)
        form.addWidget(self.date_input, 0, 1)
        point_number_widget = QWidget()
        point_number_widget.setLayout(number_box)
        form.addWidget(QLabel("N° remito"), 0, 2)
        form.addWidget(point_number_widget, 0, 3)
        form.addWidget(QLabel("Cliente"), 1, 0)
        form.addWidget(self.client_combo, 1, 1, 1, 2)
        form.addWidget(QLabel("Domicilio"), 1, 3)
        form.addWidget(self.address_combo, 1, 4, 1, 2)
        # El transporte se carga en el orden real de uso: chofer primero y
        # despues transportista, camion y acoplado (#795).
        form.addWidget(QLabel("Chofer"), 2, 0)
        form.addWidget(self.driver_combo, 2, 1)
        form.addWidget(QLabel("Transportista"), 2, 2)
        form.addWidget(self.carrier_combo, 2, 3)
        form.addWidget(QLabel("Camión"), 2, 4)
        form.addWidget(self.truck_combo, 2, 5)
        form.addWidget(QLabel("Acoplado"), 3, 0)
        form.addWidget(self.trailer_input, 3, 1)
        form.addWidget(QLabel("Doc. N° / referencia"), 3, 2)
        form.addWidget(self.reference_input, 3, 3)
        form.addWidget(QLabel("Observaciones"), 3, 4)
        form.addWidget(self.observations_input, 3, 5)
        for column in (1, 3, 5):
            form.setColumnStretch(column, 1)
        root.addWidget(header_group)

        detail_label = QLabel("Detalle de productos")
        detail_label.setObjectName("remittanceDetailTitle")
        root.addWidget(detail_label)

        self.items = QTableWidget(0, 5)
        self.items.setObjectName("remittanceItemsTable")
        self.items.setMinimumHeight(280)
        self.items.setHorizontalHeaderLabels(
            ["Producto", "Cantidad", "Precio unit.", "Descripción impresa", "Subtotal"]
        )
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        root.addWidget(self.items, 1)

        add_row = QPushButton("+ Agregar producto")
        add_row.setObjectName("addRemittanceItemButton")
        add_row.clicked.connect(self._add_item_row)
        root.addWidget(add_row)

        total_bar = QFrame()
        total_bar.setObjectName("remittanceTotalBar")
        total_bar.setFrameShape(QFrame.StyledPanel)
        total_layout = QHBoxLayout(total_bar)
        total_layout.setContentsMargins(12, 8, 12, 8)
        total_layout.setSpacing(10)
        self.total_title_label = QLabel("TOTAL GENERAL")
        self.total_title_label.setObjectName("remittanceTotalTitle")
        self.total_title_label.setStyleSheet("font-size: 13px; font-weight: 800;")
        self.total_hint_label = QLabel("")
        self.total_hint_label.setObjectName("remittanceTotalHint")
        self.total_hint_label.setStyleSheet("font-size: 11px;")
        self.total_hint_label.hide()
        self.total_value_label = QLabel("$ 0.00")
        self.total_value_label.setObjectName("remittanceTotalValue")
        self.total_value_label.setStyleSheet("font-size: 24px; font-weight: 800;")
        self.total_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_layout.addWidget(self.total_title_label)
        total_layout.addWidget(self.total_hint_label)
        total_layout.addStretch(1)
        total_layout.addWidget(self.total_value_label)
        root.addWidget(total_bar)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # La tabulacion sigue el mismo orden visual: el chofer manda sobre el
        # resto del transporte (#795).
        tab_order = (
            self.date_input,
            self.point_input,
            self.number_input,
            self.client_combo,
            self.address_combo,
            self.driver_combo,
            self.carrier_combo,
            self.truck_combo,
            self.trailer_input,
            self.reference_input,
            self.observations_input,
        )
        for first, second in zip(tab_order, tab_order[1:]):
            QWidget.setTabOrder(first, second)

        # El transporte del remito se deduce del chofer (#756).
        self._syncing_transport = False
        self._trailer_edited = False
        self.client_combo.currentIndexChanged.connect(self._refresh_addresses)
        self.truck_combo.currentIndexChanged.connect(self._suggest_trailer)
        self.driver_combo.currentIndexChanged.connect(self._refresh_from_driver)
        self.trailer_input.textEdited.connect(self._mark_trailer_edited)
        self.point_input.editingFinished.connect(self._refresh_number_availability)
        self.number_input.editingFinished.connect(self._refresh_number_availability)
        self.items.model().rowsInserted.connect(lambda *_: self._refresh_total())
        self.items.model().rowsRemoved.connect(lambda *_: self._refresh_total())
        self._load_clients()
        self._load_transport()
        if self.remittance is not None:
            self._load_remittance()
        elif self.items.rowCount() == 0:
            self._add_item_row()
        self._refresh_number_availability()
        self._refresh_total()

    @staticmethod
    def _add_search_item(combo: SearchableComboBox, label: str, value, columns: tuple) -> None:
        combo.addItem(label, value)
        combo.setItemData(combo.count() - 1, tuple(columns), SEARCH_COLUMNS_ROLE)

    def _load_clients(self) -> None:
        self.client_combo.clear()
        for client in Client.select().where(Client.active == True).order_by(Client.name):  # noqa: E712
            self._add_search_item(
                self.client_combo,
                client.name,
                client.id,
                (client.name, client.cuit or ""),
            )
        self.client_combo.setCurrentIndex(-1)
        self._resync_completer(self.client_combo)
        self._refresh_addresses()

    def _refresh_addresses(self) -> None:
        self.address_combo.clear()
        client_id = combo_current_data(self.client_combo)
        if not client_id:
            self.address_combo.setCurrentIndex(-1)
            self._resync_completer(self.address_combo)
            return
        query = (
            ClientAddress.select()
            .where((ClientAddress.client == client_id) & (ClientAddress.active == True))  # noqa: E712
            .order_by(ClientAddress.is_primary.desc(), ClientAddress.address)
        )
        for address in query:
            label = f"{address.address} - {address.city}, {address.province}"
            self._add_search_item(
                self.address_combo,
                label,
                address.id,
                (address.address, address.city, address.province),
            )
        self.address_combo.setCurrentIndex(-1)
        self._resync_completer(self.address_combo)

    @staticmethod
    def _resync_completer(combo: QComboBox) -> None:
        """Reata el completer al modelo actual del combo.

        Los items se cargan despues de habilitar el autocomplete; reatar el
        modelo deja el filtrado funcionando aunque el combo se recargue.
        """
        completer = combo.completer()
        if completer is not None:
            completer.setModel(combo.model())

    def _load_transport(self) -> None:
        self._syncing_transport = True
        try:
            for combo in (self.carrier_combo, self.truck_combo, self.driver_combo):
                combo.clear()
                self._add_search_item(combo, "Sin asignar", None, ("Sin asignar",))
            carrier_names = {carrier.id: carrier.name for carrier in Carrier.select()}
            carriers = list(
                Carrier.select().where(Carrier.active == True).order_by(Carrier.name)  # noqa: E712
            )
            for carrier in carriers:
                label = carrier.name
                if carrier.cuit:
                    label += f" · {carrier.cuit}"
                self._add_search_item(
                    self.carrier_combo,
                    label,
                    carrier.id,
                    (carrier.name, carrier.cuit or ""),
                )
            for truck in Truck.select().where(Truck.active == True).order_by(Truck.domain):  # noqa: E712
                label = truck.domain
                if truck.trailer_domain:
                    label += f" / {truck.trailer_domain}"
                carrier_name = carrier_names.get(truck.carrier_id, "")
                if carrier_name:
                    label += f" · {carrier_name}"
                self._add_search_item(
                    self.truck_combo,
                    label,
                    truck.id,
                    (truck.domain, truck.trailer_domain or "", carrier_name),
                )
            for driver in Driver.select().where(Driver.active == True).order_by(Driver.name):  # noqa: E712
                label = driver.name
                document = driver.cuit or driver.document
                if document:
                    label += f" · {document}"
                carrier_name = carrier_names.get(driver.carrier_id, "")
                self._add_search_item(
                    self.driver_combo,
                    label,
                    driver.id,
                    (driver.name, document or "", carrier_name),
                )
            for combo in (self.carrier_combo, self.truck_combo, self.driver_combo):
                combo.setCurrentIndex(-1)
        finally:
            self._syncing_transport = False
        for combo in (self.carrier_combo, self.truck_combo, self.driver_combo):
            self._resync_completer(combo)

    def _refresh_from_driver(self) -> None:
        """Completa el transporte a partir del chofer (#756).

        Igual que en las ordenes de carga: el chofer define el transportista y
        el camion habitual, y de ahi sale la patente del acoplado. El operador
        puede corregir el camion a mano; el acoplado vuelve a seguir al camion.
        """
        if self._syncing_transport:
            return
        driver_id = combo_current_data(self.driver_combo)
        if not driver_id:
            # "Sin asignar" no borra el transporte que el operador cargo a mano.
            self._set_driver_hint(DRIVER_HINT)
            return
        driver = Driver.get_or_none(driver_id)
        if driver is None:
            return
        carrier = Carrier.get_or_none(driver.carrier_id) if driver.carrier_id is not None else None
        if carrier is None:
            # El chofer no tiene transportista: no hay nada que deducir.
            self._set_driver_hint(
                "Este chofer no tiene transportista asociado: cargalo a mano."
            )
            return
        if not carrier.active:
            # El transportista esta dado de baja: no se completa nada.
            self._set_driver_hint(
                "El transportista de este chofer esta inactivo: cargalo a mano."
            )
            return
        self._set_driver_hint(DRIVER_HINT)
        index = self.carrier_combo.findData(carrier.id)
        if index >= 0:
            self.carrier_combo.setCurrentIndex(index)
        truck = self._truck_for_driver(driver, carrier)
        if truck is not None:
            index = self.truck_combo.findData(truck.id)
            if index >= 0:
                self.truck_combo.setCurrentIndex(index)
        self._suggest_trailer()

    def _set_driver_hint(self, hint: str) -> None:
        """La ayuda del combo Chofer explica que se completa y que no."""
        line_edit = self.driver_combo.lineEdit()
        if line_edit is not None:
            line_edit.setToolTip(hint)

    @staticmethod
    def _truck_for_driver(driver: Driver, carrier: Carrier) -> Truck | None:
        """El camion que corresponde al chofer: el habitual o el unico del transportista."""
        truck = (
            Truck.get_or_none(driver.usual_truck_id)
            if driver.usual_truck_id is not None
            else None
        )
        if truck is not None and truck.active:
            return truck
        trucks = list(
            Truck.select().where((Truck.active == True) & (Truck.carrier == carrier.id))  # noqa: E712
        )
        if len(trucks) == 1:
            return trucks[0]
        return None

    def _mark_trailer_edited(self, text: str) -> None:
        """La patente escrita a mano manda sobre el autocompletado.

        Si el operador borra el campo, el autocompletado vuelve a mandear.
        """
        self._trailer_edited = bool(text.strip())

    def _suggest_trailer(self) -> None:
        """El acoplado sigue al camion mientras el operador no lo escriba a mano."""
        if self._syncing_transport or self._trailer_edited:
            return
        truck_id = combo_current_data(self.truck_combo)
        trailer = None
        if truck_id:
            truck = Truck.get_or_none(truck_id)
            if truck is not None:
                trailer = truck.trailer_domain
        self.trailer_input.setText(trailer or "")

    @staticmethod
    def _selected_model(combo: QComboBox, model):
        record_id = combo_current_data(combo)
        return model.get_by_id(record_id) if record_id else None

    def _normalized_number(self) -> tuple[str | None, str | None]:
        point = self.point_input.text().strip().replace("-", "")
        number = self.number_input.text().strip().replace("-", "")
        point = point.zfill(4) if point and point.isdigit() else None
        number = number.zfill(8) if number and number.isdigit() else None
        if point is not None and len(self.point_input.text().strip().replace("-", "")) > 4:
            point = None
        if number is not None and len(self.number_input.text().strip().replace("-", "")) > 8:
            number = None
        return point, number

    def _refresh_number_availability(self) -> None:
        """Aviso en vivo si el numero de remito ya fue utilizado."""
        for field in (self.point_input, self.number_input):
            field.setStyleSheet("")
            field.setToolTip("")
        point, number = self._normalized_number()
        if not point or not number:
            return
        query = Remittance.select().where(
            (Remittance.physical_point_of_sale == point)
            & (Remittance.physical_number == number)
        )
        if self.remittance is not None:
            query = query.where(Remittance.id != self.remittance.id)
        if query.exists():
            message = f"El remito {point}-{number} ya fue utilizado. Cargue otro numero."
            for field in (self.point_input, self.number_input):
                field.setStyleSheet("border: 1px solid #c0392b;")
                field.setToolTip(message)

    def _add_item_row(self, product_id=None, quantity="", description="", unit_price=None) -> None:
        row = self.items.rowCount()
        self.items.insertRow(row)
        combo = SearchableComboBox(
            placeholder="Buscar producto...",
            search_headers=("Código", "Producto"),
        )
        combo.setObjectName(f"remittanceItemProductInput{row}")
        for product in Product.select().where(Product.active == True).order_by(Product.name):  # noqa: E712
            self._add_search_item(
                combo,
                product.name,
                product.id,
                (product.codigo or "", product.name),
            )
        self._resync_completer(combo)
        combo.setCurrentIndex(-1)
        if product_id:
            index = combo.findData(product_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        quantity_input = QLineEdit(str(quantity))
        quantity_input.setObjectName(f"remittanceItemQuantityInput{row}")
        quantity_input.setPlaceholderText("0,000")
        quantity_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        quantity_input.setValidator(QDoubleValidator(0.001, 99999999999.999, 3, quantity_input))
        # El precio se autocompleta con la lista del cliente y queda editable:
        # el operador negocia y el valor corregido es el que se congela al emitir.
        price_input = QLineEdit("" if unit_price is None else f"{unit_price:.2f}")
        price_input.setObjectName(f"remittanceItemPriceInput{row}")
        price_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        price_input.setValidator(QDoubleValidator(0, 99999999999.99, 2, price_input))
        price_input.editingFinished.connect(
            lambda r=row, w=price_input: self._autofill_price(r, w)
        )
        description_input = QLineEdit(description)
        description_input.setObjectName(f"remittanceItemDescriptionInput{row}")
        description_input.setPlaceholderText("Descripción que se imprimirá")
        subtotal_item = QTableWidgetItem("$ 0.00")
        subtotal_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        subtotal_item.setFlags(subtotal_item.flags() & ~Qt.ItemIsEditable)
        quantity_input.textChanged.connect(lambda _text: self._refresh_total())
        price_input.textChanged.connect(lambda _text: self._refresh_total())
        self.items.setCellWidget(row, 0, combo)
        self.items.setCellWidget(row, 1, quantity_input)
        self.items.setCellWidget(row, 2, price_input)
        self.items.setCellWidget(row, 3, description_input)
        self.items.setItem(row, 4, subtotal_item)
        if unit_price is None:
            self._autofill_price(row, price_input)
        self._refresh_total()

    @staticmethod
    def _decimal_from_text(text: str) -> Decimal | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return Decimal(text.replace(",", "."))
        except InvalidOperation:
            try:
                return Decimal(text.replace(".", "").replace(",", "."))
            except InvalidOperation:
                return None

    def _refresh_total(self) -> None:
        line_totals = []
        has_invalid_lines = False
        for row in range(self.items.rowCount()):
            quantity_widget = self.items.cellWidget(row, 1)
            price_widget = self.items.cellWidget(row, 2)
            subtotal_item = self.items.item(row, 4)
            quantity_text = (quantity_widget.text() if quantity_widget else "").strip()
            price_text = (price_widget.text() if price_widget else "").strip()
            if not quantity_text and not price_text:
                if subtotal_item is not None:
                    subtotal_item.setText("$ 0.00")
                continue
            quantity = self._decimal_from_text(quantity_text)
            unit_price = self._decimal_from_text(price_text)
            if quantity is None or unit_price is None or quantity < 0 or unit_price < 0:
                has_invalid_lines = True
                if subtotal_item is not None:
                    subtotal_item.setText("Revisar")
                continue
            subtotal = quantize_money(quantity * unit_price)
            line_totals.append(subtotal)
            if subtotal_item is not None:
                subtotal_item.setText(f"$ {subtotal:,.2f}")
        total = money_sum(line_totals) if line_totals else ZERO_MONEY
        if has_invalid_lines:
            hint = "Hay renglones incompletos o inválidos."
            self.total_value_label.setText("$ —")
            self.total_hint_label.setText(hint)
            self.total_hint_label.show()
            self.total_value_label.setToolTip(hint)
        else:
            self.total_value_label.setText(f"$ {total:,.2f}")
            self.total_hint_label.clear()
            self.total_hint_label.hide()
            self.total_value_label.setToolTip("")

    def _autofill_price(self, row: int, price_input: QLineEdit) -> None:
        """Sugiere el precio de la lista del cliente si el campo esta vacio."""
        if price_input.text().strip():
            return
        product_widget = self.items.cellWidget(row, 0)
        product_id = combo_current_data(product_widget) if product_widget is not None else None
        client_id = combo_current_data(self.client_combo)
        if not product_id or not client_id:
            return
        try:
            price = price_for_client_list(
                Product.get_by_id(product_id), Client.get_by_id(client_id)
            )
        except Exception:
            return
        if price:
            price_input.setText(f"{price:.2f}")

    def _load_remittance(self) -> None:
        r = self.remittance
        index = self.client_combo.findData(r.client_id)
        if index >= 0:
            self.client_combo.setCurrentIndex(index)
        self._refresh_addresses()
        index = self.address_combo.findData(r.delivery_address_id)
        if index >= 0:
            self.address_combo.setCurrentIndex(index)
        self.date_input.setDate(QDate(r.date.year, r.date.month, r.date.day))
        self.point_input.setText(r.physical_point_of_sale or "")
        self.number_input.setText(r.physical_number or "")
        self.reference_input.setText(r.document_reference or "")
        self.observations_input.setText(r.observations or "")
        # Los datos guardados mandan: la cascada del chofer no puede pisar el
        # transporte de un remito que ya existe.
        self._syncing_transport = True
        try:
            for combo, record_id in (
                (self.carrier_combo, r.carrier_id),
                (self.truck_combo, r.truck_id),
                (self.driver_combo, r.driver_id),
            ):
                index = combo.findData(record_id)
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            self._syncing_transport = False
        self.trailer_input.setText(r.trailer_domain or "")
        self.items.setRowCount(0)
        for item in r.items:
            self._add_item_row(
                item.product_id,
                item.quantity,
                item.printed_description,
                item.unit_price,
            )
        editable = r.status == Remittance.STATUS_DRAFT
        self.client_combo.setEnabled(editable)
        self.address_combo.setEnabled(editable)
        self.date_input.setEnabled(editable)
        self.point_input.setEnabled(editable)
        self.number_input.setEnabled(editable)
        self.trailer_input.setEnabled(editable)
        self.reference_input.setEnabled(editable)
        self.observations_input.setEnabled(editable)
        self.carrier_combo.setEnabled(editable)
        self.truck_combo.setEnabled(editable)
        self.driver_combo.setEnabled(editable)
        self.items.setEnabled(editable)
        self._refresh_number_availability()

    def _payload_items(self) -> list[dict]:
        payload = []
        for row in range(self.items.rowCount()):
            combo = self.items.cellWidget(row, 0)
            if combo is not None:
                commit_combo_text(combo)
            product_id = combo_current_data(combo) if combo else None
            quantity_input = self.items.cellWidget(row, 1)
            price_input = self.items.cellWidget(row, 2)
            description_input = self.items.cellWidget(row, 3)
            quantity_text = (quantity_input.text() if quantity_input else "").strip()
            price_text = (price_input.text() if price_input else "").strip()
            description = (description_input.text() if description_input else "").strip()
            if not product_id and not quantity_text and not description:
                continue
            try:
                quantity = Decimal(quantity_text.replace(",", "."))
            except (InvalidOperation, ValueError):
                raise ValueError(f"Cantidad inválida en la fila {row + 1}.") from None
            unit_price = None
            if price_text:
                try:
                    unit_price = Decimal(price_text)
                except (InvalidOperation, ValueError):
                    # Acepta tambien el formato con punto de miles y coma decimal.
                    try:
                        unit_price = Decimal(price_text.replace(".", "").replace(",", "."))
                    except (InvalidOperation, ValueError):
                        raise ValueError(f"Precio inválido en la fila {row + 1}.") from None
            payload.append(
                {
                    "product": Product.get_by_id(product_id),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "printed_description": description,
                }
            )
        return payload

    def _save(self) -> None:
        try:
            for combo in (
                self.client_combo,
                self.address_combo,
                self.carrier_combo,
                self.truck_combo,
                self.driver_combo,
            ):
                commit_combo_text(combo)
            client_id = combo_current_data(self.client_combo)
            address_id = combo_current_data(self.address_combo)
            if not client_id:
                raise ValueError("Debe seleccionar un cliente.")
            if not address_id:
                raise ValueError("Debe seleccionar un domicilio.")
            client = Client.get_by_id(client_id)
            address = ClientAddress.get_by_id(address_id)
            items = self._payload_items()
            date_value = self.date_input.date().toPyDate()
            carrier = self._selected_model(self.carrier_combo, Carrier)
            truck = self._selected_model(self.truck_combo, Truck)
            driver = self._selected_model(self.driver_combo, Driver)
            point = self.point_input.text().strip() or None
            number = self.number_input.text().strip() or None
            trailer_domain = self.trailer_input.text().strip() or None
            service = RemittanceService(self.current_user)
            if self.remittance is None:
                self.remittance = service.create_manual(
                    client=client,
                    delivery_address=address,
                    items=items,
                    remittance_date=date_value,
                    document_reference=self.reference_input.text().strip() or None,
                    observations=self.observations_input.text().strip() or None,
                    carrier=carrier,
                    truck=truck,
                    trailer_domain=trailer_domain,
                    driver=driver,
                    physical_point_of_sale=point,
                    physical_number=number,
                )
            else:
                self.remittance = service.update_draft(
                    self.remittance,
                    client=client,
                    delivery_address=address,
                    items=items,
                    date=date_value,
                    document_reference=self.reference_input.text().strip() or None,
                    observations=self.observations_input.text().strip() or None,
                    carrier=carrier,
                    truck=truck,
                    trailer_domain=trailer_domain,
                    driver=driver,
                    physical_point_of_sale=point,
                    physical_number=number,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Remito", str(exc))
            return
        self.accept()


class OrderDestinationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear remito desde Orden de carga")
        self.resize(620, 220)
        layout = QFormLayout(self)
        self.order_combo = QComboBox()
        self.destination_combo = QComboBox()
        self.order_combo.currentIndexChanged.connect(self._refresh_destinations)
        for order in LoadOrder.select().order_by(LoadOrder.order_number.desc()):
            self.order_combo.addItem(f"OC {order.order_number} - {order.status}", order.id)
        self._refresh_destinations()
        layout.addRow("Orden", self.order_combo)
        layout.addRow("Cliente / destino", self.destination_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _refresh_destinations(self) -> None:
        self.destination_combo.clear()
        order_id = self.order_combo.currentData()
        if not order_id:
            return
        order = LoadOrder.get_by_id(order_id)
        for destination in order.destinations.order_by(1):
            label = f"{destination.client.name} - {destination.delivery_address.address}"
            self.destination_combo.addItem(label, destination.id)

    def _accept_if_valid(self) -> None:
        if not self.order_combo.currentData():
            QMessageBox.warning(self, "Remito", "No hay una Orden de carga seleccionada.")
            return
        if not self.destination_combo.currentData():
            QMessageBox.warning(self, "Remito", "La Orden de carga no tiene un destino seleccionable.")
            return
        self.accept()

    def selection(self):
        if not self.order_combo.currentData() or not self.destination_combo.currentData():
            return None, None
        order = LoadOrder.get_by_id(self.order_combo.currentData())
        destination_id = self.destination_combo.currentData()
        destination = order.destinations.where(order.destinations.model.id == destination_id).first()
        return order, destination


class RemittanceSeriesDialog(QDialog):
    def __init__(self, *, current_user: str, series: RemittanceSeries | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.series = series
        self.setWindowTitle("Talonario de remitos")
        self.resize(520, 320)
        form = QFormLayout(self)
        self.name_input = QLineEdit()
        self.name_input.setObjectName("remittanceSeriesNameInput")
        self.type_input = QLineEdit("Remito R")
        self.type_input.setReadOnly(True)
        self.point_input = QLineEdit()
        self.point_input.setObjectName("remittanceSeriesPointInput")
        self.point_input.setPlaceholderText("0001")
        self.next_input = QSpinBox()
        self.next_input.setObjectName("remittanceSeriesNextInput")
        self.next_input.setRange(1, 99999999)
        self.end_input = QSpinBox()
        self.end_input.setObjectName("remittanceSeriesEndInput")
        self.end_input.setRange(0, 99999999)
        self.end_input.setSpecialValueText("Sin límite")
        self.active_input = QCheckBox("Talonario activo")
        self.active_input.setChecked(True)
        self.default_input = QCheckBox("Usar de forma predeterminada")
        self.default_input.setChecked(RemittanceSeriesService.default() is None)
        form.addRow("Nombre", self.name_input)
        form.addRow("Tipo de comprobante", self.type_input)
        form.addRow("Punto de venta", self.point_input)
        form.addRow("Próximo número", self.next_input)
        form.addRow("Número final", self.end_input)
        form.addRow(self.active_input)
        form.addRow(self.default_input)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        if series is not None:
            self.name_input.setText(series.name)
            self.point_input.setText(series.point_of_sale)
            self.next_input.setValue(series.next_number)
            self.end_input.setValue(series.end_number or 0)
            self.active_input.setChecked(series.active)
            self.default_input.setChecked(series.is_default)

    def _save(self) -> None:
        try:
            self.series = RemittanceSeriesService(self.current_user).save(
                series=self.series,
                name=self.name_input.text(),
                point_of_sale=self.point_input.text(),
                next_number=self.next_input.value(),
                end_number=self.end_input.value() or None,
                active=self.active_input.isChecked(),
                is_default=self.default_input.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Talonario de remitos", str(exc))
            return
        self.accept()


class RemittanceSeriesPage(QWidget):
    def __init__(self, *, current_user: str, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        layout = QVBoxLayout(self)
        title = QLabel("Talonarios y numeración de remitos")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        help_text = QLabel(
            "El próximo número se reserva al emitir. Los borradores no consumen hojas del talonario."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        actions = QHBoxLayout()
        new_button = QPushButton("+ Nuevo talonario")
        new_button.setObjectName("newRemittanceSeriesButton")
        edit_button = QPushButton("Editar")
        edit_button.setObjectName("editRemittanceSeriesButton")
        skip_button = QPushButton("Saltar hoja")
        skip_button.setObjectName("skipRemittanceSeriesNumberButton")
        actions.addWidget(new_button)
        actions.addWidget(edit_button)
        actions.addWidget(skip_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("remittanceSeriesTable")
        self.table.setHorizontalHeaderLabels(
            ["Talonario", "Tipo", "Punto de venta", "Próximo", "Hasta", "Estado", "Uso"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table, 1)
        new_button.clicked.connect(self._new)
        edit_button.clicked.connect(self._edit)
        skip_button.clicked.connect(self._skip)
        self.refresh()

    def refresh(self) -> None:
        rows = list(RemittanceSeries.select().order_by(RemittanceSeries.name))
        self.table.setRowCount(len(rows))
        for row, series in enumerate(rows):
            values = [
                series.name,
                series.document_type,
                series.point_of_sale,
                f"{series.next_number:08d}",
                f"{series.end_number:08d}" if series.end_number else "Sin límite",
                "Activo" if series.active else "Inactivo",
                "Predeterminado" if series.is_default else "Alternativo",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, series.id)
                self.table.setItem(row, column, item)

    def _selected(self) -> RemittanceSeries | None:
        item = self.table.item(self.table.currentRow(), 0)
        return RemittanceSeries.get_by_id(item.data(Qt.UserRole)) if item else None

    def _new(self) -> None:
        if RemittanceSeriesDialog(current_user=self.current_user, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _edit(self) -> None:
        series = self._selected()
        if series is None:
            QMessageBox.information(self, "Talonarios", "Seleccione un talonario.")
            return
        if RemittanceSeriesDialog(
            current_user=self.current_user,
            series=series,
            parent=self,
        ).exec_() == QDialog.Accepted:
            self.refresh()

    def _skip(self) -> None:
        series = self._selected()
        if series is None:
            QMessageBox.information(self, "Talonarios", "Seleccione un talonario.")
            return
        reason, accepted = QInputDialog.getMultiLineText(
            self,
            "Saltar hoja del talonario",
            f"Motivo para no utilizar {series.point_of_sale}-{series.next_number:08d}:",
        )
        if not accepted:
            return
        try:
            RemittanceSeriesService(self.current_user).skip_number(series, reason=reason)
        except Exception as exc:
            QMessageBox.warning(self, "Talonarios", str(exc))
            return
        self.refresh()


class RemittancesPage(QWidget):
    def __init__(
        self,
        *,
        current_user: str,
        parent=None,
        output_dir: Path | None = None,
        f150_output_dir: Path | None = None,
    ):
        super().__init__(parent)
        self.current_user = current_user
        self.output_dir = output_dir or REMITTANCE_PRINTS_DIR
        self.f150_output_dir = f150_output_dir or F150_OUTPUT_DIR
        layout = QVBoxLayout(self)
        title = QLabel("Remitos")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        actions = QHBoxLayout()
        new_button = QPushButton("+ Nuevo remito")
        new_button.setObjectName("newRemittanceButton")
        from_order = QPushButton("Crear desde Orden de carga")
        from_order.setObjectName("newRemittanceFromOrderButton")
        edit_button = QPushButton("Editar")
        edit_button.setObjectName("editRemittanceButton")
        issue_button = QPushButton("Emitir")
        issue_button.setObjectName("issueRemittanceButton")
        print_button = QPushButton("Imprimir formulario")
        print_button.setObjectName("printRemittanceButton")
        preview_button = QPushButton("Vista previa NO FISCAL")
        preview_button.setObjectName("previewRemittanceButton")
        history_button = QPushButton("Historial")
        history_button.setObjectName("historyRemittanceButton")
        annul_button = QPushButton("Anular")
        annul_button.setObjectName("annulRemittanceButton")
        calibration_button = QPushButton("Hoja de calibración")
        calibration_button.setObjectName("remittanceCalibrationButton")
        actions.addWidget(new_button)
        actions.addWidget(from_order)
        actions.addWidget(edit_button)
        actions.addWidget(issue_button)
        actions.addWidget(preview_button)
        actions.addWidget(print_button)
        actions.addWidget(history_button)
        actions.addWidget(annul_button)
        actions.addWidget(calibration_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("remittancesTable")
        self.table.setHorizontalHeaderLabels(
            ["Interno", "Formulario", "Fecha", "Cliente", "Destino", "Estado", "Origen"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table, 1)

        new_button.clicked.connect(self._new)
        from_order.clicked.connect(self._from_order)
        edit_button.clicked.connect(self._edit)
        issue_button.clicked.connect(self._issue)
        preview_button.clicked.connect(self._preview_selected)
        print_button.clicked.connect(self._print_selected)
        history_button.clicked.connect(self._history_selected)
        annul_button.clicked.connect(self._annul_selected)
        calibration_button.clicked.connect(self._print_calibration)
        self.refresh()

    def refresh(self) -> None:
        rows = list(Remittance.select().order_by(Remittance.id.desc()))
        self.table.setRowCount(len(rows))
        for row, remittance in enumerate(rows):
            physical = ""
            if remittance.physical_point_of_sale and remittance.physical_number:
                physical = f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
            values = [
                remittance.remittance_number,
                physical,
                remittance.date.strftime("%d/%m/%Y"),
                remittance.client_name,
                f"{remittance.delivery_address_text} - {remittance.delivery_city or ''}",
                remittance.status,
                f"OC {remittance.source_order.order_number}" if remittance.source_order_id else "Manual",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, remittance.id)
                self.table.setItem(row, col, item)

    def _selected(self) -> Remittance | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return Remittance.get_by_id(item.data(Qt.UserRole)) if item else None

    def _new(self) -> None:
        if RemittanceDialog(current_user=self.current_user, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _from_order(self) -> None:
        selector = OrderDestinationDialog(self)
        if selector.exec_() != QDialog.Accepted:
            return
        order, destination = selector.selection()
        if order is None or destination is None:
            return
        try:
            remittance = RemittanceService(self.current_user).create_from_order(
                order=order,
                destination=destination,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito creado",
            f"Se creó {remittance.remittance_number} en borrador. Complete el número del formulario antes de emitir.",
        )

    def _edit(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        if remittance.status != Remittance.STATUS_DRAFT:
            QMessageBox.information(self, "Remitos", "Solo los remitos en borrador pueden editarse.")
            return
        if RemittanceDialog(current_user=self.current_user, remittance=remittance, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _issue(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        try:
            emitted = RemittanceService(self.current_user).issue(remittance)
        except Exception as exc:
            QMessageBox.warning(self, "Emitir remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito emitido",
            f"{emitted.remittance_number} quedó emitido y ya no puede editarse.",
        )
        self._generate_f150_after_emit(emitted)

    def _generate_f150_after_emit(self, remittance: Remittance) -> None:
        """Genera el F150 del remito recien emitido, sin preguntar.

        Cargar el remito con sus datos y que el F150 aparezca es el flujo normal.
        Si falta un dato del formato no se cae la emision: el remito queda
        pendiente y aparece en la pantalla de F150 con el motivo, para
        generarlo mas tarde una vez completados los datos.
        """
        if not remittance.physical_point_of_sale or not remittance.physical_number:
            return
        identity = f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
        file_name = f"F150-{remittance.physical_point_of_sale}-{remittance.physical_number}.txt"
        output = self.f150_output_dir / file_name
        try:
            batch = F150BatchService(self.current_user).generate([remittance], output)
        except FileExistsError:
            # Ya se habia generado. No es un problema para el operador.
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "F150 pendiente",
                f"El remito {identity} quedo emitido, pero su F150 no se genero:\n\n"
                f"{exc}\n\n"
                "El remito aparece en la pantalla de F150 para generarlo cuando "
                "complete los datos que faltan.",
            )
            return
        QMessageBox.information(
            self,
            "F150 generado",
            f"Se generó {batch.file_name} en:\n{output}",
        )

    def _print_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        physical = (
            f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
            if remittance.physical_point_of_sale and remittance.physical_number
            else remittance.remittance_number
        )
        output = self.output_dir / f"remito_{physical.replace('-', '_')}.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_preprinted(
                remittance,
                output,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Imprimir remito", str(exc))
            return
        self._open_pdf(pdf_path)

    def _preview_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        output = self.output_dir / f"vista_previa_{remittance.remittance_number.replace('-', '_')}.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_preview(
                remittance,
                output,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Vista previa de remito", str(exc))
            return
        self._open_pdf(pdf_path)

    def _history_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        RemittanceHistoryDialog(remittance, self).exec_()

    def _annul_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        if remittance.status == Remittance.STATUS_ANNULLED:
            QMessageBox.information(self, "Remitos", "El remito seleccionado ya está anulado.")
            return
        dialog = AuditReasonDialog(
            title=f"Anular {remittance.remittance_number}",
            prompt=(
                "Indique el motivo de la anulación. El remito original y su "
                "evolución permanecerán en el historial."
            ),
            confirm_text="Anular remito",
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            annulled = RemittanceService(self.current_user).annul(
                remittance,
                reason=dialog.reason(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Anular remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito anulado",
            f"{annulled.remittance_number} quedó anulado.",
        )

    def _print_calibration(self) -> None:
        output = self.output_dir / "calibracion_remito_preimpreso.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_calibration(output)
        except Exception as exc:
            QMessageBox.warning(self, "Calibración de remito", str(exc))
            return
        self._open_pdf(pdf_path)

    @staticmethod
    def _open_pdf(path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.information(
                None,
                "Remitos",
                f"El PDF se generó correctamente en:\n{path}",
            )

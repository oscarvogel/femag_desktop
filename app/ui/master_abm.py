from __future__ import annotations

from dataclasses import dataclass

from peewee import InterfaceError, OperationalError
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.client_service import ClientService
from app.services.master_service import MasterService
from app.services.permission_service import PermissionService


AUTO_ABM_TECHNICAL_DEBT = (
    "Issue #70 keeps these master screens as a minimal local PyQt adapter. "
    "They do not instantiate pyqt5libs AutoABM yet because pyqt5libs is not "
    "importable in the current validation environment and the generated ABM "
    "needs a FEMAG-specific adapter for permissions, audit services and "
    "foreign-key combo labels before it can replace this screen safely."
)


@dataclass(frozen=True)
class MasterAbmConfig:
    title: str
    columns: list[str]
    rows_fn: object
    dialog_class: type[QDialog]
    new_button_name: str
    edit_button_name: str


def build_master_abm_page(
    *,
    config: MasterAbmConfig,
    user,
    current_user: str,
    parent=None,
) -> QWidget:
    page = _page(config.title, "ABM minimo para operar Ordenes de carga")
    layout = page.layout()
    feedback = QLabel("")
    feedback.setObjectName(f"{config.new_button_name}Feedback")
    feedback.setToolTip(AUTO_ABM_TECHNICAL_DEBT)
    actions = QHBoxLayout()
    new_button = _action_button(config.new_button_name, "Nuevo")
    edit_button = _action_button(config.edit_button_name, "Editar", secondary=True)
    can_create = _can_use_menu_action(user, "Maestros", "crear", config.title)
    can_modify = _can_use_menu_action(user, "Maestros", "modificar", config.title)
    new_button.setEnabled(can_create)
    edit_button.setEnabled(can_modify)
    if not can_create:
        new_button.setToolTip("El perfil actual no permite crear este maestro.")
    if not can_modify:
        edit_button.setToolTip("El perfil actual no permite modificar este maestro.")
    actions.addWidget(new_button)
    actions.addWidget(edit_button)
    actions.addStretch(1)
    layout.addLayout(actions)
    table = QTableWidget(0, len(config.columns))
    table.setObjectName(f"{config.new_button_name}Table")
    table.setHorizontalHeaderLabels(config.columns)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    layout.addWidget(table, 1)
    layout.addWidget(feedback)

    def refresh() -> None:
        rows = config.rows_fn()
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            row_id, values = row[0], row[1:]
            for column, value in enumerate(values):
                table.setItem(row_index, column, QTableWidgetItem(str(value)))
            if table.item(row_index, 0):
                table.item(row_index, 0).setData(Qt.UserRole, row_id)
        if rows:
            table.setCurrentCell(0, 0)

    def selected_id() -> int | None:
        item = table.item(table.currentRow(), 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def open_new() -> None:
        if not can_create:
            feedback.setText("El perfil actual no permite crear este maestro.")
            return
        dialog = config.dialog_class(current_user=current_user, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh()
            feedback.setText("Registro guardado.")

    def open_edit() -> None:
        if not can_modify:
            feedback.setText("El perfil actual no permite modificar este maestro.")
            return
        row_id = selected_id()
        if row_id is None:
            feedback.setText("Seleccione un registro para editar.")
            return
        dialog = config.dialog_class(current_user=current_user, record_id=row_id, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh()
            feedback.setText("Registro actualizado.")

    new_button.clicked.connect(open_new)
    edit_button.clicked.connect(open_edit)
    refresh()
    return page


def master_abm_configs() -> dict[str, MasterAbmConfig]:
    return {
        "clients": MasterAbmConfig(
            "Clientes",
            ["Nombre", "CUIT", "Estado"],
            _client_rows,
            ClientEntryDialog,
            "newClientButton",
            "editClientButton",
        ),
        "addresses": MasterAbmConfig(
            "Domicilios",
            ["Cliente", "Tipo", "Localidad", "Direccion"],
            _address_rows,
            ClientAddressEntryDialog,
            "newAddressButton",
            "editAddressButton",
        ),
        "products": MasterAbmConfig(
            "Productos",
            ["Producto", "Unidad", "Estado"],
            _product_rows,
            ProductEntryDialog,
            "newProductButton",
            "editProductButton",
        ),
        "drivers": MasterAbmConfig(
            "Choferes",
            ["Nombre", "Transportista", "Estado"],
            _driver_rows,
            DriverEntryDialog,
            "newDriverButton",
            "editDriverButton",
        ),
        "carriers": MasterAbmConfig(
            "Transportistas",
            ["Nombre", "CUIT", "Telefono", "Estado"],
            _carrier_rows,
            CarrierEntryDialog,
            "newCarrierButton",
            "editCarrierButton",
        ),
        "trucks": MasterAbmConfig(
            "Camiones",
            ["Patente", "Transportista", "Estado"],
            _truck_rows,
            TruckEntryDialog,
            "newTruckButton",
            "editTruckButton",
        ),
    }


class ClientEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Client | None = None
        self.setObjectName("clientEntryDialog")
        self.setWindowTitle("Cliente")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Cliente")
        form = QGridLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("clientNameInput")
        self.cuit_input = QLineEdit()
        self.cuit_input.setObjectName("clientCuitInput")
        self.iva_input = QLineEdit()
        self.iva_input.setObjectName("clientIvaInput")
        self.phone_input = QLineEdit()
        self.phone_input.setObjectName("clientPhoneInput")
        form.addWidget(QLabel("Nombre"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("CUIT"), 1, 0)
        form.addWidget(self.cuit_input, 1, 1)
        form.addWidget(QLabel("IVA"), 2, 0)
        form.addWidget(self.iva_input, 2, 1)
        form.addWidget(QLabel("Telefono"), 3, 0)
        form.addWidget(self.phone_input, 3, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveClientButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            self.iva_input.setText("RI")
            return
        client = Client.get_by_id(self.record_id)
        self.name_input.setText(client.name)
        self.cuit_input.setText(client.cuit)
        self.iva_input.setText(client.iva_condition)
        self.phone_input.setText(client.phone or "")

    def _save(self) -> None:
        name = self.name_input.text().strip()
        cuit = self.cuit_input.text().strip()
        iva = self.iva_input.text().strip()
        if not name or not cuit or not iva:
            self.feedback.setText("Complete nombre, CUIT e IVA.")
            return
        try:
            if self.record_id is None:
                self.saved_record = ClientService(self.current_user).create_client(
                    name,
                    cuit,
                    iva,
                    phone=self.phone_input.text().strip() or None,
                )
            else:
                client = Client.get_by_id(self.record_id)
                client.name = name
                client.cuit = cuit
                client.iva_condition = iva
                client.phone = self.phone_input.text().strip() or None
                client.save()
                self.saved_record = client
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class ClientAddressEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: ClientAddress | None = None
        self.setObjectName("clientAddressEntryDialog")
        self.setWindowTitle("Domicilio")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Domicilio de entrega")
        form = QGridLayout()
        self.client_combo = _combo("addressClientInput", _client_options())
        self.type_combo = _combo(
            "addressTypeInput",
            [("entrega", "Entrega"), ("fiscal", "Fiscal")],
            include_empty=False,
        )
        self.province_input = QLineEdit()
        self.province_input.setObjectName("addressProvinceInput")
        self.city_input = QLineEdit()
        self.city_input.setObjectName("addressCityInput")
        self.street_input = QLineEdit()
        self.street_input.setObjectName("addressStreetInput")
        form.addWidget(QLabel("Cliente"), 0, 0)
        form.addWidget(self.client_combo, 0, 1)
        form.addWidget(QLabel("Tipo"), 1, 0)
        form.addWidget(self.type_combo, 1, 1)
        form.addWidget(QLabel("Provincia"), 2, 0)
        form.addWidget(self.province_input, 2, 1)
        form.addWidget(QLabel("Ciudad"), 3, 0)
        form.addWidget(self.city_input, 3, 1)
        form.addWidget(QLabel("Direccion"), 4, 0)
        form.addWidget(self.street_input, 4, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveAddressButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        address = ClientAddress.get_by_id(self.record_id)
        _set_combo(self.client_combo, address.client.id)
        _set_combo(self.type_combo, address.address_type)
        self.province_input.setText(address.province)
        self.city_input.setText(address.city)
        self.street_input.setText(address.address)

    def _save(self) -> None:
        client_id = self.client_combo.currentData()
        province = self.province_input.text().strip()
        city = self.city_input.text().strip()
        street = self.street_input.text().strip()
        if client_id is None or not province or not city or not street:
            self.feedback.setText("Complete cliente, provincia, ciudad y direccion.")
            return
        try:
            client = Client.get_by_id(client_id)
            address_type = self.type_combo.currentData() or "entrega"
            if self.record_id is None:
                self.saved_record = ClientService(self.current_user).add_address(
                    client,
                    address_type,
                    province,
                    city,
                    street,
                    is_primary=address_type == "entrega",
                )
            else:
                address = ClientAddress.get_by_id(self.record_id)
                address.client = client
                address.address_type = address_type
                address.province = province
                address.city = city
                address.address = street
                address.save()
                self.saved_record = address
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class CarrierEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Carrier | None = None
        self.setObjectName("carrierEntryDialog")
        self.setWindowTitle("Transportista")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Transportista")
        form = QGridLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("carrierNameInput")
        self.cuit_input = QLineEdit()
        self.cuit_input.setObjectName("carrierCuitInput")
        self.phone_input = QLineEdit()
        self.phone_input.setObjectName("carrierPhoneInput")
        form.addWidget(QLabel("Nombre"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("CUIT"), 1, 0)
        form.addWidget(self.cuit_input, 1, 1)
        form.addWidget(QLabel("Telefono"), 2, 0)
        form.addWidget(self.phone_input, 2, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveCarrierButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        carrier = Carrier.get_by_id(self.record_id)
        self.name_input.setText(carrier.name)
        self.cuit_input.setText(carrier.cuit or "")
        self.phone_input.setText(carrier.phone or "")

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.feedback.setText("Complete el nombre del transportista.")
            return
        try:
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_carrier(
                    name,
                    cuit=self.cuit_input.text().strip() or None,
                    phone=self.phone_input.text().strip() or None,
                )
            else:
                carrier = Carrier.get_by_id(self.record_id)
                carrier.name = name
                carrier.cuit = self.cuit_input.text().strip() or None
                carrier.phone = self.phone_input.text().strip() or None
                carrier.save()
                self.saved_record = carrier
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class DriverEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Driver | None = None
        self.setObjectName("driverEntryDialog")
        self.setWindowTitle("Chofer")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Chofer")
        form = QGridLayout()
        self.carrier_combo = _combo("driverCarrierInput", _carrier_options())
        self.name_input = QLineEdit()
        self.name_input.setObjectName("driverNameInput")
        self.document_input = QLineEdit()
        self.document_input.setObjectName("driverDocumentInput")
        self.phone_input = QLineEdit()
        self.phone_input.setObjectName("driverPhoneInput")
        form.addWidget(QLabel("Transportista"), 0, 0)
        form.addWidget(self.carrier_combo, 0, 1)
        form.addWidget(QLabel("Nombre"), 1, 0)
        form.addWidget(self.name_input, 1, 1)
        form.addWidget(QLabel("Documento"), 2, 0)
        form.addWidget(self.document_input, 2, 1)
        form.addWidget(QLabel("Telefono"), 3, 0)
        form.addWidget(self.phone_input, 3, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveDriverButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        driver = Driver.get_by_id(self.record_id)
        _set_combo(self.carrier_combo, driver.carrier.id)
        self.name_input.setText(driver.name)
        self.document_input.setText(driver.document or "")
        self.phone_input.setText(driver.phone or "")

    def _save(self) -> None:
        carrier_id = self.carrier_combo.currentData()
        name = self.name_input.text().strip()
        if carrier_id is None or not name:
            self.feedback.setText("Complete transportista y nombre del chofer.")
            return
        try:
            carrier = Carrier.get_by_id(carrier_id)
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_driver(
                    name,
                    carrier=carrier,
                    document=self.document_input.text().strip() or None,
                    phone=self.phone_input.text().strip() or None,
                )
            else:
                driver = Driver.get_by_id(self.record_id)
                driver.name = name
                driver.carrier = carrier
                driver.document = self.document_input.text().strip() or None
                driver.phone = self.phone_input.text().strip() or None
                driver.save()
                self.saved_record = driver
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class TruckEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Truck | None = None
        self.setObjectName("truckEntryDialog")
        self.setWindowTitle("Camion")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Camion / patente")
        form = QGridLayout()
        self.carrier_combo = _combo("truckCarrierInput", _carrier_options())
        self.domain_input = QLineEdit()
        self.domain_input.setObjectName("truckDomainInput")
        self.active_combo = _combo("truckActiveInput", [(True, "Activo"), (False, "Inactivo")], include_empty=False)
        form.addWidget(QLabel("Transportista"), 0, 0)
        form.addWidget(self.carrier_combo, 0, 1)
        form.addWidget(QLabel("Patente"), 1, 0)
        form.addWidget(self.domain_input, 1, 1)
        form.addWidget(QLabel("Estado"), 2, 0)
        form.addWidget(self.active_combo, 2, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveTruckButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        truck = Truck.get_by_id(self.record_id)
        _set_combo(self.carrier_combo, truck.carrier.id)
        self.domain_input.setText(truck.domain)
        _set_combo(self.active_combo, truck.active)

    def _save(self) -> None:
        carrier_id = self.carrier_combo.currentData()
        domain = self.domain_input.text().strip().upper()
        if carrier_id is None and not _carrier_options():
            self.feedback.setText("Debe cargar un transportista antes de crear un camión.")
            return
        if carrier_id is None or not domain:
            self.feedback.setText("Complete transportista y patente.")
            return
        try:
            carrier = Carrier.get_by_id(carrier_id)
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_truck(domain, carrier=carrier)
            else:
                truck = Truck.get_by_id(self.record_id)
                truck.domain = domain
                truck.carrier = carrier
                truck.active = bool(self.active_combo.currentData())
                truck.save()
                self.saved_record = truck
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class ProductEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Product | None = None
        self.setObjectName("productEntryDialog")
        self.setWindowTitle("Producto")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Producto / presentacion")
        form = QGridLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("productNameInput")
        self.unit_input = QLineEdit()
        self.unit_input.setObjectName("productUnitInput")
        form.addWidget(QLabel("Producto"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("Unidad"), 1, 0)
        form.addWidget(self.unit_input, 1, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveProductButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            self.unit_input.setText("kg")
            return
        product = Product.get_by_id(self.record_id)
        self.name_input.setText(product.name)
        self.unit_input.setText(product.unit)

    def _save(self) -> None:
        name = self.name_input.text().strip()
        unit = self.unit_input.text().strip()
        if not name or not unit:
            self.feedback.setText("Complete producto y unidad.")
            return
        try:
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_product(name, unit)
            else:
                product = Product.get_by_id(self.record_id)
                product.name = name
                product.unit = unit
                product.save()
                self.saved_record = product
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


def _page(title: str, subtitle: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(26, 22, 26, 22)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("pageSubtitle")
    layout.addWidget(title_label)
    layout.addWidget(subtitle_label)
    return page


def _action_button(object_name: str, text: str, *, secondary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    if secondary:
        button.setProperty("secondary", True)
    return button


def _entry_layout(dialog: QDialog, title: str) -> QVBoxLayout:
    dialog.resize(520, 260)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(16, 16, 16, 14)
    layout.setSpacing(10)
    title_label = QLabel(title)
    title_label.setObjectName("dialogTitle")
    layout.addWidget(title_label)
    return layout


def _entry_feedback(layout: QVBoxLayout) -> QLabel:
    feedback = QLabel("")
    feedback.setObjectName("masterDialogFeedback")
    feedback.setWordWrap(True)
    layout.addWidget(feedback)
    return feedback


def _entry_footer(layout: QVBoxLayout, dialog: QDialog, save_object_name: str, save_callback) -> None:
    footer = QHBoxLayout()
    footer.addStretch(1)
    cancel_button = _action_button(f"cancel{save_object_name}", "Cancelar", secondary=True)
    save_button = _action_button(save_object_name, "Guardar")
    footer.addWidget(cancel_button)
    footer.addWidget(save_button)
    layout.addLayout(footer)
    cancel_button.clicked.connect(dialog.reject)
    save_button.clicked.connect(save_callback)


def _combo(object_name: str, options: list[tuple[object, str]], *, include_empty: bool = False) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName(object_name)
    _fill_combo(combo, options, include_empty=include_empty)
    return combo


def _fill_combo(combo: QComboBox, options: list[tuple[object, str]], *, include_empty: bool = True) -> None:
    combo.clear()
    if include_empty:
        combo.addItem("", None)
    for value, label in options:
        combo.addItem(label, value)


def _set_combo(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _can_use_menu_action(user, section: str, action: str, title: str) -> bool:
    if user is None:
        return False
    try:
        return PermissionService().has_permission(user, section, action, title)
    except (InterfaceError, OperationalError):
        return False


def _client_options() -> list[tuple[int, str]]:
    try:
        return [(client.id, client.name) for client in Client.select().where(Client.active == True).order_by(Client.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _carrier_options() -> list[tuple[int, str]]:
    try:
        return [(carrier.id, carrier.name) for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _client_rows() -> list[list[object]]:
    try:
        return [
            [client.id, client.name, client.cuit, "Activo" if client.active else "Inactivo"]
            for client in Client.select().order_by(Client.name).limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []


def _address_rows() -> list[list[object]]:
    try:
        return [
            [address.id, address.client.name, address.address_type, address.city, address.address]
            for address in ClientAddress.select()
            .join(Client)
            .order_by(Client.name, ClientAddress.city)
            .limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []


def _product_rows() -> list[list[object]]:
    try:
        return [
            [product.id, product.name, product.unit, "Activo" if product.active else "Inactivo"]
            for product in Product.select().order_by(Product.name).limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []


def _driver_rows() -> list[list[object]]:
    try:
        return [
            [
                driver.id,
                driver.name,
                driver.carrier.name,
                "Disponible" if driver.available and driver.active else "No disponible",
            ]
            for driver in Driver.select().join(Carrier).order_by(Driver.name).limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []


def _carrier_rows() -> list[list[object]]:
    try:
        return [
            [carrier.id, carrier.name, carrier.cuit or "", carrier.phone or "", "Activo" if carrier.active else "Inactivo"]
            for carrier in Carrier.select().order_by(Carrier.name).limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []


def _truck_rows() -> list[list[object]]:
    try:
        return [
            [truck.id, truck.domain, truck.carrier.name, "Activo" if truck.active else "Inactivo"]
            for truck in Truck.select().join(Carrier).order_by(Truck.domain).limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from peewee import JOIN, InterfaceError, OperationalError
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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

from app.models.masters import (
    CLIENT_ADDRESS_TYPE_DELIVERY,
    CLIENT_ADDRESS_TYPE_FISCAL,
    CLIENT_ADDRESS_TYPE_SHARED,
    PRODUCT_KIND_LABELS,
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    TipoIVA,
    Truck,
    client_address_has_delivery_function,
    client_address_type_label,
    product_is_loadable,
    product_kind_label,
)
from app.services.client_service import ClientService
from app.services.master_service import MasterService
from app.services.permission_service import PermissionService
from app.ui.combo_autocomplete import combo_current_data, enable_combo_autocomplete


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
    sort_column: int = 0
    search_placeholder: str = ""


def normalize_master_text(value: object) -> str:
    """Return a comparison key shared by master-table search and sorting."""
    text = unicodedata.normalize("NFKD", "" if value is None else str(value))
    return "".join(character for character in text.casefold() if character.isalnum())


def filter_and_sort_master_rows(
    rows: list[list[object]],
    *,
    query: str = "",
    sort_column: int = 0,
    descending: bool = False,
) -> list[list[object]]:
    """Filter visible row values and sort them deterministically for an ABM table."""
    normalized_query = normalize_master_text(query)
    visible_rows = [
        row
        for row in rows
        if not normalized_query
        or normalized_query in normalize_master_text(" ".join(str(value) for value in row[1:]))
    ]
    # Use the record id as the stable tie-breaker in both directions.
    visible_rows.sort(key=lambda row: row[0])
    visible_rows.sort(
        key=lambda row: normalize_master_text(
            row[sort_column + 1] if sort_column + 1 < len(row) else ""
        ),
        reverse=descending,
    )
    return visible_rows


class MasterTableController:
    """Reusable search/sort behavior for the master ABM tables."""

    def __init__(
        self,
        *,
        table: QTableWidget,
        search_input: QLineEdit,
        search_feedback: QLabel,
        rows_fn,
        sort_column: int = 0,
    ):
        self.table = table
        self.search_input = search_input
        self.search_feedback = search_feedback
        self.rows_fn = rows_fn
        self.sort_column = sort_column
        self.sort_order = Qt.AscendingOrder
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self.sort_column, self.sort_order)
        header.sectionClicked.connect(self._toggle_sort)
        self.search_input.textChanged.connect(self.refresh)

    def _toggle_sort(self, column: int) -> None:
        if column == self.sort_column:
            self.sort_order = (
                Qt.DescendingOrder
                if self.sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(self.sort_column, self.sort_order)
        self.refresh()

    def selected_id(self) -> int | None:
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item is not None else None

    def refresh(self) -> None:
        selected_id = self.selected_id()
        rows = filter_and_sort_master_rows(
            list(self.rows_fn()),
            query=self.search_input.text(),
            sort_column=self.sort_column,
            descending=self.sort_order == Qt.DescendingOrder,
        )
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            row_id, values = row[0], row[1:]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
            if self.table.item(row_index, 0):
                self.table.item(row_index, 0).setData(Qt.UserRole, row_id)

        if rows:
            selected_row = next(
                (index for index, row in enumerate(rows) if row[0] == selected_id),
                0,
            )
            self.table.setCurrentCell(selected_row, 0)

        query = self.search_input.text().strip()
        if query and not rows:
            self.search_feedback.setText(f"No se encontraron coincidencias para «{query}».")
        else:
            self.search_feedback.setText("")


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
    search_input = QLineEdit()
    search_input.setObjectName(f"{config.new_button_name}SearchInput")
    search_input.setClearButtonEnabled(True)
    search_input.setPlaceholderText(
        config.search_placeholder or f"Buscar {config.title.lower()}..."
    )
    search_row = QHBoxLayout()
    search_row.addWidget(QLabel("Buscar"))
    search_row.addWidget(search_input, 1)
    layout.addLayout(search_row)
    search_feedback = QLabel("")
    search_feedback.setObjectName(f"{config.new_button_name}SearchFeedback")
    layout.addWidget(search_feedback)
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

    table_controller = MasterTableController(
        table=table,
        search_input=search_input,
        search_feedback=search_feedback,
        rows_fn=config.rows_fn,
        sort_column=config.sort_column,
    )

    def open_new() -> None:
        if not can_create:
            feedback.setText("El perfil actual no permite crear este maestro.")
            return
        dialog = config.dialog_class(current_user=current_user, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            table_controller.refresh()
            feedback.setText("Registro guardado.")

    def open_edit() -> None:
        if not can_modify:
            feedback.setText("El perfil actual no permite modificar este maestro.")
            return
        row_id = table_controller.selected_id()
        if row_id is None:
            feedback.setText("Seleccione un registro para editar.")
            return
        dialog = config.dialog_class(current_user=current_user, record_id=row_id, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            table_controller.refresh()
            feedback.setText("Registro actualizado.")

    new_button.clicked.connect(open_new)
    edit_button.clicked.connect(open_edit)
    page.master_table_controller = table_controller
    page.refresh = table_controller.refresh
    table_controller.refresh()
    return page


def master_abm_configs() -> dict[str, MasterAbmConfig]:
    return {
        "clients": MasterAbmConfig(
            "Clientes",
            ["Nombre", "CUIT", "Lista", "Estado"],
            _client_rows,
            ClientEntryDialog,
            "newClientButton",
            "editClientButton",
            search_placeholder="Buscar clientes por nombre o CUIT...",
        ),
        "addresses": MasterAbmConfig(
            "Domicilios",
            ["Cliente", "Tipo", "Localidad", "Direccion", "Estado"],
            _address_rows,
            ClientAddressEntryDialog,
            "newAddressButton",
            "editAddressButton",
            search_placeholder="Buscar domicilios por cliente, ciudad o dirección...",
        ),
        "products": MasterAbmConfig(
            "Productos",
            ["Producto", "Unidad", "Peso", "Clasificación", "Órdenes", "Revisión", "Lista 1", "Lista 2", "Lista 3", "Lista 4", "Estado"],
            _product_rows,
            ProductEntryDialog,
            "newProductButton",
            "editProductButton",
            search_placeholder="Buscar productos por nombre...",
        ),
        "vat_types": MasterAbmConfig(
            "Tipos de IVA",
            ["Nombre", "Porcentaje", "Estado"],
            _vat_type_rows,
            VatTypeEntryDialog,
            "newVatTypeButton",
            "editVatTypeButton",
            search_placeholder="Buscar tipos de IVA...",
        ),
        "drivers": MasterAbmConfig(
            "Choferes",
            ["Nombre", "Transportista", "Tractor", "Acoplado", "Estado de relación"],
            _driver_rows,
            DriverEntryDialog,
            "newDriverButton",
            "editDriverButton",
            search_placeholder="Buscar choferes por nombre o transportista...",
        ),
        "carriers": MasterAbmConfig(
            "Transportistas",
            ["Nombre", "CUIT", "Telefono", "Estado"],
            _carrier_rows,
            CarrierEntryDialog,
            "newCarrierButton",
            "editCarrierButton",
            search_placeholder="Buscar transportistas por nombre o razón social...",
        ),
        "trucks": MasterAbmConfig(
            "Camiones",
            ["Patente tractor", "Patente acoplado", "Transportista", "Estado"],
            _truck_rows,
            TruckEntryDialog,
            "newTruckButton",
            "editTruckButton",
            search_placeholder="Buscar camiones por patente o transportista...",
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
        self.price_list_combo = _combo("clientPriceListInput", _price_list_options(), include_empty=False)
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
        _set_combo(self.price_list_combo, client.lista_precios)

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
                    lista_precios=int(self.price_list_combo.currentData() or 1),
                )
            else:
                client = Client.get_by_id(self.record_id)
                client.name = name
                client.cuit = cuit
                client.iva_condition = iva
                client.phone = self.phone_input.text().strip() or None
                client.lista_precios = int(self.price_list_combo.currentData() or 1)
                client.save()
                self.saved_record = client
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class ClientAddressEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, client_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.client_id = client_id
        self.saved_record: ClientAddress | None = None
        self.setObjectName("clientAddressEntryDialog")
        self.setWindowTitle("Domicilio")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Domicilio")
        form = QGridLayout()
        self.client_combo = _combo("addressClientInput", _client_options())
        self.type_combo = _combo(
            "addressTypeInput",
            [
                (CLIENT_ADDRESS_TYPE_DELIVERY, client_address_type_label(CLIENT_ADDRESS_TYPE_DELIVERY)),
                (CLIENT_ADDRESS_TYPE_FISCAL, client_address_type_label(CLIENT_ADDRESS_TYPE_FISCAL)),
                (CLIENT_ADDRESS_TYPE_SHARED, client_address_type_label(CLIENT_ADDRESS_TYPE_SHARED)),
            ],
            include_empty=False,
        )
        self.province_input = QLineEdit()
        self.province_input.setObjectName("addressProvinceInput")
        self.city_input = QLineEdit()
        self.city_input.setObjectName("addressCityInput")
        self.street_input = QLineEdit()
        self.street_input.setObjectName("addressStreetInput")
        self.active_combo = _combo("addressActiveInput", [(True, "Activo"), (False, "Inactivo")], include_empty=False)
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
        form.addWidget(QLabel("Estado"), 5, 0)
        form.addWidget(self.active_combo, 5, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveAddressButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is not None:
            address = ClientAddress.get_by_id(self.record_id)
            _set_combo(self.client_combo, address.client.id)
            _set_combo(self.type_combo, address.address_type)
            _set_combo(self.active_combo, address.active)
            self.province_input.setText(address.province)
            self.city_input.setText(address.city)
            self.street_input.setText(address.address)
            return
        if self.client_id is not None:
            _set_combo(self.client_combo, self.client_id)

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
                    is_primary=client_address_has_delivery_function(address_type),
                )
            else:
                address = ClientAddress.get_by_id(self.record_id)
                self.saved_record = ClientService(self.current_user).update_address(
                    address,
                    client=client,
                    address_type=address_type,
                    province=province,
                    city=city,
                    address=street,
                    active=bool(self.active_combo.currentData()),
                )
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
        self.usual_truck_combo = _combo("driverUsualTruckInput", _truck_master_options())
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
        form.addWidget(QLabel("Camión habitual"), 2, 0)
        form.addWidget(self.usual_truck_combo, 2, 1)
        form.addWidget(QLabel("Documento"), 3, 0)
        form.addWidget(self.document_input, 3, 1)
        form.addWidget(QLabel("Telefono"), 4, 0)
        form.addWidget(self.phone_input, 4, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveDriverButton", self._save)
        self.carrier_combo.currentIndexChanged.connect(self._refresh_truck_options)

    def _refresh_truck_options(self) -> None:
        current_truck_id = self.usual_truck_combo.currentData()
        carrier_id = combo_current_data(self.carrier_combo)
        _fill_combo(
            self.usual_truck_combo,
            _truck_master_options(carrier_id),
            include_empty=True,
        )
        if current_truck_id is not None:
            _set_combo(self.usual_truck_combo, current_truck_id)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        driver = Driver.get_by_id(self.record_id)
        if driver.carrier_id is not None:
            _set_combo(self.carrier_combo, driver.carrier_id)
        self._refresh_truck_options()
        if driver.usual_truck_id is not None:
            _set_combo(self.usual_truck_combo, driver.usual_truck_id)
        self.name_input.setText(driver.name)
        self.document_input.setText(driver.document or "")
        self.phone_input.setText(driver.phone or "")

    def _save(self) -> None:
        carrier_id = combo_current_data(self.carrier_combo)
        name = self.name_input.text().strip()
        if carrier_id is None or not name:
            self.feedback.setText("Complete transportista y nombre del chofer.")
            return
        try:
            carrier = Carrier.get_by_id(carrier_id)
            usual_truck_id = self.usual_truck_combo.currentData()
            usual_truck = Truck.get_by_id(usual_truck_id) if usual_truck_id is not None else None
            if usual_truck is not None and usual_truck.carrier_id not in {None, carrier.id}:
                self.feedback.setText("El camión habitual pertenece a otro transportista.")
                return
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_driver(
                    name,
                    carrier=carrier,
                    usual_truck=usual_truck,
                    document=self.document_input.text().strip() or None,
                    phone=self.phone_input.text().strip() or None,
                )
            else:
                driver = Driver.get_by_id(self.record_id)
                driver.name = name
                driver.carrier = carrier
                driver.usual_truck = usual_truck
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
        self.trailer_domain_input = QLineEdit()
        self.trailer_domain_input.setObjectName("truckTrailerDomainInput")
        self.active_combo = _combo("truckActiveInput", [(True, "Activo"), (False, "Inactivo")], include_empty=False)
        form.addWidget(QLabel("Transportista"), 0, 0)
        form.addWidget(self.carrier_combo, 0, 1)
        form.addWidget(QLabel("Patente"), 1, 0)
        form.addWidget(self.domain_input, 1, 1)
        form.addWidget(QLabel("Patente acoplado"), 2, 0)
        form.addWidget(self.trailer_domain_input, 2, 1)
        form.addWidget(QLabel("Estado"), 3, 0)
        form.addWidget(self.active_combo, 3, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveTruckButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        truck = Truck.get_by_id(self.record_id)
        if truck.carrier_id is not None:
            _set_combo(self.carrier_combo, truck.carrier_id)
        self.domain_input.setText(truck.domain)
        self.trailer_domain_input.setText(truck.trailer_domain or "")
        _set_combo(self.active_combo, truck.active)

    def _save(self) -> None:
        carrier_id = self.carrier_combo.currentData()
        domain = _normalize_domain(self.domain_input.text())
        trailer_domain = _normalize_domain(self.trailer_domain_input.text()) or None
        if carrier_id is None and not _carrier_options():
            self.feedback.setText("Debe cargar un transportista antes de crear un camión.")
            return
        if carrier_id is None or not domain:
            self.feedback.setText("Complete transportista y patente.")
            return
        try:
            carrier = Carrier.get_by_id(carrier_id)
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_truck(
                    domain,
                    carrier=carrier,
                    trailer_domain=trailer_domain,
                )
            else:
                truck = Truck.get_by_id(self.record_id)
                truck.domain = domain
                truck.trailer_domain = trailer_domain
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
        self.weight_input = QDoubleSpinBox()
        self.weight_input.setObjectName("productWeightKgInput")
        self.weight_input.setRange(0, 999999999)
        self.weight_input.setDecimals(3)
        self.weight_input.setSuffix(" kg")
        self.kind_input = QComboBox()
        self.kind_input.setObjectName("productKindInput")
        enable_combo_autocomplete(self.kind_input, placeholder="Buscar tipo...")
        for value, label in PRODUCT_KIND_LABELS.items():
            self.kind_input.addItem(label, value)
        self.iva_input = QComboBox()
        self.iva_input.setObjectName("productIvaTypeInput")
        enable_combo_autocomplete(self.iva_input, placeholder="Buscar IVA...")
        iva_default = TipoIVA.iva_default()
        for tipo_iva in TipoIVA.select().where(TipoIVA.activo == True).order_by(TipoIVA.nombre):  # noqa: E712
            self.iva_input.addItem(f"{tipo_iva.nombre} ({tipo_iva.porcentaje:g}%)", tipo_iva.id)
        default_index = self.iva_input.findData(iva_default.id)
        if default_index >= 0:
            self.iva_input.setCurrentIndex(default_index)
        self.price_list_1_input = QLineEdit()
        self.price_list_1_input.setObjectName("productPriceList1Input")
        self.price_list_2_input = QLineEdit()
        self.price_list_2_input.setObjectName("productPriceList2Input")
        self.price_list_3_input = QLineEdit()
        self.price_list_3_input.setObjectName("productPriceList3Input")
        self.price_list_4_input = QLineEdit()
        self.price_list_4_input.setObjectName("productPriceList4Input")
        form.addWidget(QLabel("Producto"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("Clasificación"), 1, 0)
        form.addWidget(self.kind_input, 1, 1)
        form.addWidget(QLabel("Unidad"), 2, 0)
        form.addWidget(self.unit_input, 2, 1)
        form.addWidget(QLabel("Peso unitario"), 3, 0)
        form.addWidget(self.weight_input, 3, 1)
        form.addWidget(QLabel("Tipo de IVA"), 4, 0)
        form.addWidget(self.iva_input, 4, 1)
        form.addWidget(QLabel("Lista 1"), 5, 0)
        form.addWidget(self.price_list_1_input, 5, 1)
        form.addWidget(QLabel("Lista 2"), 6, 0)
        form.addWidget(self.price_list_2_input, 6, 1)
        form.addWidget(QLabel("Lista 3"), 7, 0)
        form.addWidget(self.price_list_3_input, 7, 1)
        form.addWidget(QLabel("Lista 4"), 8, 0)
        form.addWidget(self.price_list_4_input, 8, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveProductButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            self.unit_input.setText("kg")
            return
        product = Product.get_by_id(self.record_id)
        if product.tipo_iva_id is not None and self.iva_input.findData(product.tipo_iva_id) < 0:
            tipo_iva = product.tipo_iva
            self.iva_input.addItem(
                f"{tipo_iva.nombre} ({tipo_iva.porcentaje:g}%) — Inactivo",
                tipo_iva.id,
            )
        self.name_input.setText(product.name)
        self.unit_input.setText(product.unit)
        self.weight_input.setValue(float(product.peso_unitario_kg))
        self.kind_input.setCurrentIndex(max(self.kind_input.findData(product.product_kind or "revisar"), 0))
        if product.tipo_iva_id is not None:
            self.iva_input.setCurrentIndex(self.iva_input.findData(product.tipo_iva_id))
        self.price_list_1_input.setText(_money_text(product.precio_lista_1 or product.precio_neto_base))
        self.price_list_2_input.setText(_money_text(product.precio_lista_2))
        self.price_list_3_input.setText(_money_text(product.precio_lista_3))
        self.price_list_4_input.setText(_money_text(product.precio_lista_4))

    def _save(self) -> None:
        name = self.name_input.text().strip()
        unit = self.unit_input.text().strip()
        if not name or not unit:
            self.feedback.setText("Complete producto y unidad.")
            return
        try:
            prices = {
                "precio_lista_1": _parse_float(self.price_list_1_input.text()),
                "precio_lista_2": _parse_float(self.price_list_2_input.text()),
                "precio_lista_3": _parse_float(self.price_list_3_input.text()),
                "precio_lista_4": _parse_float(self.price_list_4_input.text()),
            }
            tipo_iva_id = self.iva_input.currentData()
            tipo_iva = TipoIVA.get_by_id(tipo_iva_id) if tipo_iva_id is not None else None
            if self.record_id is None:
                self.saved_record = MasterService(self.current_user).create_product(
                    name,
                    unit,
                    peso_unitario_kg=Decimal(str(self.weight_input.value())),
                    product_kind=self.kind_input.currentData(),
                    tipo_iva=tipo_iva,
                    **prices,
                )
            else:
                self.saved_record = MasterService(self.current_user).update_product(
                    Product.get_by_id(self.record_id), name, unit,
                    peso_unitario_kg=Decimal(str(self.weight_input.value())),
                    product_kind=self.kind_input.currentData(),
                    tipo_iva=tipo_iva,
                    **prices,
                )
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class VatTypeEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: TipoIVA | None = None
        self.setObjectName("vatTypeEntryDialog")
        self.setWindowTitle("Tipo de IVA")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Tipo de IVA")
        form = QGridLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("vatTypeNameInput")
        self.percentage_input = QDoubleSpinBox()
        self.percentage_input.setObjectName("vatTypePercentageInput")
        self.percentage_input.setRange(0, 100)
        self.percentage_input.setDecimals(2)
        self.percentage_input.setSuffix(" %")
        self.active_input = QComboBox()
        self.active_input.setObjectName("vatTypeActiveInput")
        enable_combo_autocomplete(self.active_input, placeholder="Buscar estado...")
        self.active_input.addItem("Activo", True)
        self.active_input.addItem("Inactivo", False)
        form.addWidget(QLabel("Nombre"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("Porcentaje"), 1, 0)
        form.addWidget(self.percentage_input, 1, 1)
        form.addWidget(QLabel("Estado"), 2, 0)
        form.addWidget(self.active_input, 2, 1)
        layout.addLayout(form)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveVatTypeButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            return
        tipo_iva = TipoIVA.get_by_id(self.record_id)
        self.name_input.setText(tipo_iva.nombre)
        self.percentage_input.setValue(tipo_iva.porcentaje)
        self.active_input.setCurrentIndex(max(self.active_input.findData(tipo_iva.activo), 0))

    def _save(self) -> None:
        try:
            service = MasterService(self.current_user)
            if self.record_id is None:
                self.saved_record = service.create_tipo_iva(
                    self.name_input.text(),
                    self.percentage_input.value(),
                    activo=bool(self.active_input.currentData()),
                )
            else:
                self.saved_record = service.update_tipo_iva(
                    TipoIVA.get_by_id(self.record_id),
                    self.name_input.text(),
                    self.percentage_input.value(),
                    activo=bool(self.active_input.currentData()),
                )
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
    enable_combo_autocomplete(combo)
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


def _price_list_options() -> list[tuple[int, str]]:
    return [(1, "Lista 1"), (2, "Lista 2"), (3, "Lista 3"), (4, "Lista 4")]


def _parse_float(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    return float(normalized) if normalized else 0.0


def _money_text(value: float | None) -> str:
    value = value or 0.0
    return f"{value:g}"


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


def _truck_master_options(carrier_id: int | None = None) -> list[tuple[int, str]]:
    try:
        query = Truck.select().where(Truck.active == True)  # noqa: E712
        if carrier_id is not None:
            query = query.where((Truck.carrier == carrier_id) | Truck.carrier.is_null(True))
        return [
            (
                truck.id,
                f"{truck.domain} · {truck.trailer_domain}" if truck.trailer_domain else truck.domain,
            )
            for truck in query.order_by(Truck.domain)
        ]
    except (InterfaceError, OperationalError):
        return []


def _normalize_domain(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def _client_rows() -> list[list[object]]:
    try:
        return [
            [client.id, client.name, client.cuit, f"Lista {client.lista_precios}", "Activo" if client.active else "Inactivo"]
            for client in Client.select().order_by(Client.name)
        ]
    except (InterfaceError, OperationalError):
        return []


def _address_rows() -> list[list[object]]:
    try:
        return [
            [
                address.id,
                address.client.name,
                client_address_type_label(address.address_type),
                address.city,
                address.address,
                "Activo" if address.active else "Inactivo",
            ]
            for address in ClientAddress.select()
            .join(Client)
            .order_by(Client.name, ClientAddress.city)
        ]
    except (InterfaceError, OperationalError):
        return []


def _product_rows() -> list[list[object]]:
    try:
        return [
            [
                product.id,
                product.name,
                product.unit,
                (
                    f"{product.peso_unitario_kg:.3f} kg"
                    if product.peso_unitario_kg > 0
                    else "Peso pendiente"
                ),
                product_kind_label(product.product_kind),
                "Sí" if product_is_loadable(product) else "No",
                "Pendiente" if product.review_required else "Confirmado",
                _money_text(product.precio_lista_1 or product.precio_neto_base),
                _money_text(product.precio_lista_2),
                _money_text(product.precio_lista_3),
                _money_text(product.precio_lista_4),
                "Activo" if product.active else "Inactivo",
            ]
            for product in Product.select().order_by(Product.name)
        ]
    except (InterfaceError, OperationalError):
        return []


def _vat_type_rows() -> list[list[object]]:
    try:
        return [
            [
                tipo_iva.id,
                tipo_iva.nombre,
                f"{tipo_iva.porcentaje:g}%",
                "Activo" if tipo_iva.activo else "Inactivo",
            ]
            for tipo_iva in TipoIVA.select().order_by(TipoIVA.nombre)
        ]
    except (InterfaceError, OperationalError):
        return []


def _driver_rows() -> list[list[object]]:
    try:
        rows = []
        for driver in Driver.select().order_by(Driver.name):
            truck = driver.usual_truck if driver.usual_truck_id is not None else None
            if driver.carrier_id is None:
                relationship_state = "Sin transportista"
            elif truck is None:
                relationship_state = "Sin tractor"
            else:
                relationship_state = "Completa"
            rows.append(
                [
                    driver.id,
                    driver.name,
                    driver.carrier.name if driver.carrier_id is not None else "Sin asignar",
                    truck.domain if truck is not None else "",
                    (truck.trailer_domain or "") if truck is not None else "",
                    relationship_state,
                ]
            )
        return rows
    except (InterfaceError, OperationalError):
        return []


def _carrier_rows() -> list[list[object]]:
    try:
        return [
            [carrier.id, carrier.name, carrier.cuit or "", carrier.phone or "", "Activo" if carrier.active else "Inactivo"]
            for carrier in Carrier.select().order_by(Carrier.name)
        ]
    except (InterfaceError, OperationalError):
        return []


def _truck_rows() -> list[list[object]]:
    try:
        return [
            [
                truck.id,
                truck.domain,
                truck.trailer_domain or "",
                truck.carrier.name if truck.carrier_id is not None else "Sin asignar",
                "Activo" if truck.active else "Inactivo",
            ]
            for truck in Truck.select().order_by(Truck.domain)
        ]
    except (InterfaceError, OperationalError):
        return []


def _client_address_rows(client_id: int) -> list[list[object]]:
    try:
        return [
            [
                address.id,
                client_address_type_label(address.address_type),
                address.address,
                address.city,
                address.province,
                "Activo" if address.active else "Inactivo",
            ]
            for address in ClientAddress.select()
            .where(ClientAddress.client == client_id)
            .order_by(ClientAddress.address)
        ]
    except (InterfaceError, OperationalError):
        return []


def build_client_abm_page(*, user, current_user: str, parent=None) -> QWidget:
    page = _page("Clientes", "ABM de clientes con domicilios")
    layout = page.layout()
    can_create = _can_use_menu_action(user, "Maestros", "crear", "Clientes")
    can_modify = _can_use_menu_action(user, "Maestros", "modificar", "Clientes")

    client_feedback = QLabel("")
    client_feedback.setObjectName("clientAbmFeedback")

    client_search_input = QLineEdit()
    client_search_input.setObjectName("clientSearchInput")
    client_search_input.setClearButtonEnabled(True)
    client_search_input.setPlaceholderText("Buscar clientes por nombre o CUIT...")
    client_search_row = QHBoxLayout()
    client_search_row.addWidget(QLabel("Buscar"))
    client_search_row.addWidget(client_search_input, 1)
    layout.addLayout(client_search_row)
    client_search_feedback = QLabel("")
    client_search_feedback.setObjectName("clientSearchFeedback")
    layout.addWidget(client_search_feedback)

    client_actions = QHBoxLayout()
    new_client_btn = _action_button("newClientButton", "Nuevo")
    edit_client_btn = _action_button("editClientButton", "Editar", secondary=True)
    new_client_btn.setEnabled(can_create)
    edit_client_btn.setEnabled(can_modify)
    client_actions.addWidget(new_client_btn)
    client_actions.addWidget(edit_client_btn)
    client_actions.addStretch(1)
    layout.addLayout(client_actions)

    client_table = QTableWidget(0, 4)
    client_table.setObjectName("clientTable")
    client_table.setHorizontalHeaderLabels(["Nombre", "CUIT", "Lista", "Estado"])
    client_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    client_table.verticalHeader().setVisible(False)
    client_table.setSelectionBehavior(QTableWidget.SelectRows)
    layout.addWidget(client_table, 1)

    separator = QLabel("Domicilios")
    separator.setObjectName("sectionTitle")
    layout.addWidget(separator)

    places_search_input = QLineEdit()
    places_search_input.setObjectName("clientPlacesSearchInput")
    places_search_input.setClearButtonEnabled(True)
    places_search_input.setPlaceholderText("Buscar domicilios por ciudad, dirección o estado...")
    places_search_row = QHBoxLayout()
    places_search_row.addWidget(QLabel("Buscar domicilios"))
    places_search_row.addWidget(places_search_input, 1)
    layout.addLayout(places_search_row)
    places_search_feedback = QLabel("")
    places_search_feedback.setObjectName("clientPlacesSearchFeedback")
    layout.addWidget(places_search_feedback)

    places_feedback = QLabel("")
    places_feedback.setObjectName("clientPlacesFeedback")

    place_actions = QHBoxLayout()
    add_place_btn = _action_button("addClientPlaceButton", "Agregar")
    edit_place_btn = _action_button("editClientPlaceButton", "Editar", secondary=True)
    toggle_place_btn = _action_button("toggleClientPlaceButton", "Activar/Desactivar", secondary=True)
    place_actions.addWidget(add_place_btn)
    place_actions.addWidget(edit_place_btn)
    place_actions.addWidget(toggle_place_btn)
    place_actions.addStretch(1)
    layout.addLayout(place_actions)

    places_table = QTableWidget(0, 5)
    places_table.setObjectName("clientPlacesTable")
    places_table.setHorizontalHeaderLabels(["Tipo", "Direccion", "Ciudad", "Provincia", "Estado"])
    places_header = places_table.horizontalHeader()
    places_header.setSectionResizeMode(QHeaderView.Stretch)
    places_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    places_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
    places_table.verticalHeader().setVisible(False)
    places_table.setSelectionBehavior(QTableWidget.SelectRows)
    layout.addWidget(places_table, 1)
    layout.addWidget(places_feedback)

    def refresh_clients() -> None:
        client_table_controller.refresh()
        refresh_places()

    def selected_client_id() -> int | None:
        item = client_table.item(client_table.currentRow(), 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def refresh_places() -> None:
        cid = selected_client_id()
        if cid is None:
            places_table.setRowCount(0)
            places_search_feedback.setText("")
            places_feedback.setText("Seleccione un cliente para ver sus domicilios.")
            return
        places_table_controller.refresh()
        rows = _client_address_rows(cid)
        if not rows:
            places_feedback.setText("Este cliente no tiene domicilios cargados.")
        else:
            places_feedback.setText("")

    client_table_controller = MasterTableController(
        table=client_table,
        search_input=client_search_input,
        search_feedback=client_search_feedback,
        rows_fn=_client_rows,
    )
    places_table_controller = MasterTableController(
        table=places_table,
        search_input=places_search_input,
        search_feedback=places_search_feedback,
        rows_fn=lambda: _client_address_rows(selected_client_id())
        if selected_client_id() is not None
        else [],
        sort_column=1,
    )

    def open_new_client() -> None:
        if not can_create:
            client_feedback.setText("El perfil actual no permite crear este maestro.")
            return
        dialog = ClientEntryDialog(current_user=current_user, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh_clients()
            client_feedback.setText("Cliente guardado.")

    def open_edit_client() -> None:
        if not can_modify:
            client_feedback.setText("El perfil actual no permite modificar este maestro.")
            return
        cid = selected_client_id()
        if cid is None:
            client_feedback.setText("Seleccione un cliente para editar.")
            return
        dialog = ClientEntryDialog(current_user=current_user, record_id=cid, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh_clients()
            client_feedback.setText("Cliente actualizado.")

    def open_new_place() -> None:
        cid = selected_client_id()
        if cid is None:
            places_feedback.setText("Seleccione un cliente primero.")
            return
        dialog = ClientAddressEntryDialog(current_user=current_user, client_id=cid, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh_places()
            places_feedback.setText("Lugar de entrega guardado.")

    def open_edit_place() -> None:
        item = places_table.item(places_table.currentRow(), 0)
        if item is None:
            places_feedback.setText("Seleccione un lugar de entrega para editar.")
            return
        pid = item.data(Qt.UserRole)
        dialog = ClientAddressEntryDialog(current_user=current_user, record_id=pid, parent=parent)
        if dialog.exec_() == QDialog.Accepted:
            refresh_places()
            places_feedback.setText("Lugar de entrega actualizado.")

    def toggle_place_active() -> None:
        item = places_table.item(places_table.currentRow(), 0)
        if item is None:
            places_feedback.setText("Seleccione un lugar de entrega para activar o desactivar.")
            return
        pid = item.data(Qt.UserRole)
        address = ClientAddress.get_by_id(pid)
        address.active = not address.active
        address.save()
        refresh_places()
        status = "activado" if address.active else "desactivado"
        places_feedback.setText(f"Lugar de entrega {status}.")

    new_client_btn.clicked.connect(open_new_client)
    edit_client_btn.clicked.connect(open_edit_client)
    add_place_btn.clicked.connect(open_new_place)
    edit_place_btn.clicked.connect(open_edit_place)
    toggle_place_btn.clicked.connect(toggle_place_active)
    client_table.currentCellChanged.connect(lambda *_: refresh_places())

    page.client_table_controller = client_table_controller
    page.client_places_table_controller = places_table_controller
    page.refresh = refresh_clients
    refresh_clients()
    return page

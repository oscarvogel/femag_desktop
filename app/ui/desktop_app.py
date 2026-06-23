from __future__ import annotations

from pathlib import Path

from peewee import InterfaceError, OperationalError, SqliteDatabase
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.database import bind_database, initialize_runtime_database
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.services.auth_service import AuthService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_form_spec
from app.ui.main_window import MainWindow as ShellBuilder
from scripts.seed_demo_data import DEMO_DB_PATH, seed_demo_data


def run_desktop_app(*, demo_mode: bool = False) -> int:
    database = _prepare_database(demo_mode=demo_mode)
    if database is not None:
        PermissionService().seed_defaults()
        user = _demo_user()
    else:
        user = None
    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=user, demo_mode=demo_mode or database is None)
    window.show()
    result = app.exec_()
    if database is not None and not database.is_closed():
        database.close()
    return result


def _prepare_database(*, demo_mode: bool):
    if demo_mode:
        seed_demo_data()
        database = SqliteDatabase(DEMO_DB_PATH)
        bind_database(database)
        database.connect(reuse_if_open=True)
        return database
    try:
        database = initialize_runtime_database()
        database.connect(reuse_if_open=True)
        return database
    except Exception:
        return None


class FemagDesktopWindow(QMainWindow):
    def __init__(self, *, user, demo_mode: bool):
        super().__init__()
        self.shell = ShellBuilder(user=user, demo_mode=demo_mode).shell_spec
        self.setWindowTitle("FEMAG Desktop")
        self.resize(1280, 820)
        self.setStyleSheet(STYLES)
        self.stack = QStackedWidget()
        self.nav = QListWidget()
        self._route_indexes: dict[str, int] = {}
        self._build()

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar(), 0)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._statusbar())

        self.setCentralWidget(root)
        self._add_page("dashboard", self._dashboard_page())
        self._add_page("clients", self._table_page("Clientes", ["Nombre", "CUIT", "Estado"], _client_rows()))
        self._add_page("products", self._table_page("Productos", ["Producto", "Unidad", "Estado"], _product_rows()))
        self._add_page("drivers", self._table_page("Choferes", ["Nombre", "Teléfono", "Disponible"], _driver_rows()))
        self._add_page("load_orders", self._load_order_page())
        self._add_page("placeholder", self._placeholder_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(1)

    def _topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        title = QLabel(self.shell.app_name)
        title.setObjectName("appTitle")
        subtitle = QLabel(self.shell.subtitle)
        user = QLabel(f"{self.shell.username} · {self.shell.profile} · {self.shell.connection_state}")
        user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        layout.addWidget(user)
        return bar

    def _sidebar(self) -> QListWidget:
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(260)
        for section in self.shell.sidebar.sections if self.shell.sidebar else []:
            header = QListWidgetItem(section.title)
            header.setFlags(Qt.NoItemFlags)
            self.nav.addItem(header)
            for item in section.items:
                row = QListWidgetItem(f"  {item.title}")
                route = item.route_key or "placeholder"
                row.setData(Qt.UserRole, route)
                if item.placeholder:
                    row.setForeground(Qt.gray)
                    row.setToolTip(item.disabled_reason or future_module_message())
                self.nav.addItem(row)
        return self.nav

    def _statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusbar")
        layout = QHBoxLayout(bar)
        layout.addWidget(
            QLabel(
                f"{self.shell.status_bar.version} · {self.shell.status_bar.state} · "
                f"Último backup {self.shell.status_bar.last_backup}"
            )
        )
        return bar

    def _add_page(self, route: str, widget: QWidget) -> None:
        self._route_indexes[route] = self.stack.addWidget(widget)

    def _navigate(self, row: int) -> None:
        item = self.nav.item(row)
        if not item:
            return
        route = item.data(Qt.UserRole)
        if route in self._route_indexes:
            self.stack.setCurrentIndex(self._route_indexes[route])

    def _dashboard_page(self) -> QWidget:
        spec = DashboardService().view_spec(demo_mode=True)
        page = _page(spec.title)
        layout = page.layout()
        actions = QHBoxLayout()
        for action in spec.quick_actions:
            button = QPushButton(action.title)
            button.setEnabled(action.enabled)
            button.setMinimumHeight(52)
            actions.addWidget(button)
        layout.addLayout(actions)
        cards = QGridLayout()
        for index, (title, value) in enumerate(spec.summary_cards.items()):
            cards.addWidget(_card(title, str(value)), index // 3, index % 3)
        layout.addLayout(cards)
        layout.addWidget(QLabel("Pendientes y alertas"))
        for alert in spec.alerts:
            layout.addWidget(QLabel(f"• {alert}"))
        layout.addStretch(1)
        return page

    def _table_page(self, title: str, columns: list[str], rows: list[list[str]]) -> QWidget:
        page = _page(title)
        layout = page.layout()
        layout.addWidget(QLabel(f"Buscar en {title.lower()}..."))
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(value))
        layout.addWidget(table)
        layout.addStretch(1)
        return page

    def _load_order_page(self) -> QWidget:
        spec = build_load_order_form_spec()
        page = _page("Órdenes de carga")
        page.setObjectName("loadOrdersPage")
        layout = page.layout()
        service = LoadOrderService(current_user=self.shell.username)
        print_service = LoadOrderPrintService(current_user=self.shell.username)
        selected_order_id: dict[str, int | None] = {"value": None}

        table = QTableWidget(0, 9)
        table.setObjectName("loadOrdersTable")
        table.setHorizontalHeaderLabels(
            ["Número", "Fecha", "Cliente", "Destino", "Producto", "Cantidad", "Pallets", "Chofer", "Estado"]
        )
        layout.addWidget(table)

        form_frame = QFrame()
        form_frame.setObjectName("card")
        form = QGridLayout(form_frame)
        form.addWidget(QLabel(spec.sections[0].title), 0, 0)
        form.addWidget(QLabel(spec.sections[1].title), 0, 1)

        data_form = QFormLayout()
        transport_form = QFormLayout()
        order_number = QLineEdit()
        order_number.setObjectName("orderNumberInput")
        order_number.setReadOnly(True)
        order_date = QDateEdit(QDate.currentDate())
        order_date.setObjectName("orderDateInput")
        order_date.setCalendarPopup(True)
        client_combo = _combo("clientCombo", _client_options())
        address_combo = _combo("addressCombo", _address_options())
        product_combo = _combo("productCombo", _product_options())
        quantity = QLineEdit()
        quantity.setObjectName("quantityInput")
        quantity.setPlaceholderText("Cantidad mayor a cero")
        pallet_combo = _combo("palletCombo", _pallet_options(), include_empty=True)
        pallet_quantity = QLineEdit()
        pallet_quantity.setObjectName("palletQuantityInput")
        pallet_quantity.setPlaceholderText("Pallets")
        observations = QLineEdit()
        observations.setObjectName("observationsInput")
        status_combo = _combo(
            "statusCombo",
            [
                (LoadOrder.STATUS_DRAFT, LoadOrder.STATUS_DRAFT),
                (LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_ISSUED),
                (LoadOrder.STATUS_ANNULLED, LoadOrder.STATUS_ANNULLED),
            ],
        )

        carrier_combo = _combo("carrierCombo", _carrier_options())
        truck_combo = _combo("truckCombo", _truck_options())
        driver_combo = _combo("driverCombo", _driver_options())
        data_form.addRow("Número de orden", order_number)
        data_form.addRow("Fecha", order_date)
        data_form.addRow("Cliente", client_combo)
        data_form.addRow("Domicilio de entrega", address_combo)
        data_form.addRow("Producto", product_combo)
        data_form.addRow("Cantidad", quantity)
        data_form.addRow("Pallet", pallet_combo)
        data_form.addRow("Cantidad pallets", pallet_quantity)
        data_form.addRow("Estado", status_combo)
        transport_form.addRow("Transportista", carrier_combo)
        transport_form.addRow("Camión / patente", truck_combo)
        transport_form.addRow("Chofer", driver_combo)
        transport_form.addRow("Observaciones", observations)
        form.addLayout(data_form, 1, 0)
        form.addLayout(transport_form, 1, 1)
        layout.addWidget(form_frame)

        feedback = QLabel("")
        feedback.setObjectName("loadOrderFeedback")
        layout.addWidget(feedback)

        actions = QHBoxLayout()
        new_button = _action_button("newLoadOrderButton", "Nueva")
        save_button = _action_button("saveLoadOrderButton", "Guardar")
        issue_button = _action_button("issueLoadOrderButton", "Emitir")
        annul_button = _action_button("annulLoadOrderButton", "Anular")
        print_button = _action_button("printLoadOrderButton", "Imprimir A4")
        for button in (new_button, save_button, issue_button, annul_button, print_button):
            actions.addWidget(button)
        layout.addLayout(actions)

        def refresh() -> None:
            rows = service.list_orders()
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                table.setItem(row_index, 0, QTableWidgetItem(str(row["numero"])))
                table.setItem(row_index, 1, QTableWidgetItem(row["fecha"].strftime("%d/%m/%Y")))
                table.setItem(row_index, 2, QTableWidgetItem(row["cliente"]))
                table.setItem(row_index, 3, QTableWidgetItem(row["destino"]))
                table.setItem(row_index, 4, QTableWidgetItem(row["producto"]))
                table.setItem(row_index, 5, QTableWidgetItem(f'{row["cantidad"]:g}'))
                table.setItem(row_index, 6, QTableWidgetItem(str(row["pallets"])))
                table.setItem(row_index, 7, QTableWidgetItem(row["chofer"]))
                table.setItem(row_index, 8, QTableWidgetItem(row["estado"]))
                table.item(row_index, 0).setData(Qt.UserRole, row["id"])

        def clear_form() -> None:
            selected_order_id["value"] = None
            order_number.clear()
            order_date.setDate(QDate.currentDate())
            quantity.clear()
            pallet_quantity.clear()
            observations.clear()
            _set_combo(status_combo, LoadOrder.STATUS_DRAFT)
            feedback.setText("")

        def selected_order() -> LoadOrder | None:
            if selected_order_id["value"] is None:
                return None
            return LoadOrder.get_by_id(selected_order_id["value"])

        def load_selected(row: int) -> None:
            item = table.item(row, 0)
            if item is None:
                return
            order = LoadOrder.get_by_id(item.data(Qt.UserRole))
            selected_order_id["value"] = order.id
            first_product = order.products.first()
            first_pallet = order.pallets.first()
            order_number.setText(str(order.order_number))
            order_date.setDate(QDate(order.date.year, order.date.month, order.date.day))
            _set_combo(client_combo, order.client.id)
            _set_combo(address_combo, order.delivery_address.id)
            _set_combo(carrier_combo, order.carrier.id)
            _set_combo(truck_combo, order.truck.id)
            _set_combo(driver_combo, order.driver.id)
            _set_combo(status_combo, order.status)
            observations.setText(order.observations or "")
            if first_product is not None:
                _set_combo(product_combo, first_product.product.id)
                quantity.setText(f"{first_product.quantity:g}")
            if first_pallet is not None:
                _set_combo(pallet_combo, first_pallet.pallet_type.id)
                pallet_quantity.setText(str(first_pallet.quantity))

        def payload() -> dict:
            product = Product.get_by_id(product_combo.currentData())
            pallets = []
            if pallet_combo.currentData() and pallet_quantity.text().strip():
                pallets.append(
                    {
                        "pallet_type": PalletType.get_by_id(pallet_combo.currentData()),
                        "quantity": int(pallet_quantity.text().strip()),
                    }
                )
            return {
                "client": Client.get_by_id(client_combo.currentData()),
                "delivery_address": ClientAddress.get_by_id(address_combo.currentData()),
                "carrier": Carrier.get_by_id(carrier_combo.currentData()),
                "driver": Driver.get_by_id(driver_combo.currentData()),
                "truck": Truck.get_by_id(truck_combo.currentData()),
                "order_date": order_date.date().toPyDate(),
                "products": [{"product": product, "quantity": float(quantity.text().strip())}],
                "pallets": pallets,
                "observations": observations.text().strip() or None,
            }

        def save() -> None:
            try:
                order = selected_order()
                if order is None:
                    order = service.create_order(**payload())
                else:
                    order = service.update_order(order, **payload())
                desired_status = status_combo.currentData()
                if desired_status != order.status:
                    if desired_status == LoadOrder.STATUS_ANNULLED:
                        order = service.annul_order(order, can_annul=True, reason="Anulada desde pantalla")
                    else:
                        order = service.change_status(order, desired_status, reason="Actualizada desde pantalla")
                feedback.setText(f"Orden {order.order_number} guardada.")
                selected_order_id["value"] = order.id
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def issue() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para emitir.")
                return
            try:
                service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida desde pantalla")
                feedback.setText(f"Orden {order.order_number} emitida.")
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def annul() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para anular.")
                return
            try:
                service.annul_order(order, can_annul=True, reason="Anulada desde pantalla")
                feedback.setText(f"Orden {order.order_number} anulada.")
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def print_order() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para imprimir.")
                return
            path = print_service.export_combined(order, Path("docs") / "prints")
            feedback.setText(f"Vista A4 generada: {path}")

        table.currentCellChanged.connect(lambda row, _column, _previous_row, _previous_column: load_selected(row))
        new_button.clicked.connect(clear_form)
        save_button.clicked.connect(save)
        issue_button.clicked.connect(issue)
        annul_button.clicked.connect(annul)
        print_button.clicked.connect(print_order)
        refresh()
        return page

    def _placeholder_page(self) -> QWidget:
        page = _page("Módulo futuro")
        page.layout().addWidget(QLabel(future_module_message()))
        page.layout().addStretch(1)
        return page


def _page(title: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    heading = QLabel(title)
    heading.setObjectName("heading")
    layout.addWidget(heading)
    return page


def _card(title: str, value: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.addWidget(QLabel(title))
    value_label = QLabel(value)
    value_label.setObjectName("cardValue")
    layout.addWidget(value_label)
    return frame


def _action_button(object_name: str, text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    return button


def _combo(object_name: str, options: list[tuple[object, str]], *, include_empty: bool = False) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName(object_name)
    if include_empty:
        combo.addItem("", None)
    for value, label in options:
        combo.addItem(label, value)
    return combo


def _set_combo(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _client_options() -> list[tuple[int, str]]:
    try:
        return [(client.id, client.name) for client in Client.select().where(Client.active == True).order_by(Client.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _address_options() -> list[tuple[int, str]]:
    try:
        return [
            (address.id, f"{address.client.name} - {address.address}, {address.city}")
            for address in ClientAddress.select().join(Client).order_by(Client.name, ClientAddress.city)
        ]
    except (InterfaceError, OperationalError):
        return []


def _product_options() -> list[tuple[int, str]]:
    try:
        return [(product.id, product.name) for product in Product.select().where(Product.active == True).order_by(Product.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _carrier_options() -> list[tuple[int, str]]:
    try:
        return [(carrier.id, carrier.name) for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _truck_options() -> list[tuple[int, str]]:
    try:
        return [(truck.id, truck.domain) for truck in Truck.select().where(Truck.active == True).order_by(Truck.domain)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _driver_options() -> list[tuple[int, str]]:
    try:
        return [(driver.id, driver.name) for driver in Driver.select().where(Driver.active == True).order_by(Driver.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _pallet_options() -> list[tuple[int, str]]:
    try:
        return [(pallet.id, pallet.type) for pallet in PalletType.select().where(PalletType.active == True).order_by(PalletType.type)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _demo_user():
    service = AuthService()
    user = service.authenticate("demo_visual", "demo")
    if user:
        return user
    return service.create_user("demo_visual", "demo", "Administrador")


def _client_rows() -> list[list[str]]:
    try:
        return [[client.name, client.cuit, "Activo" if client.active else "Inactivo"] for client in Client.select().limit(20)]
    except (InterfaceError, OperationalError):
        return []


def _product_rows() -> list[list[str]]:
    try:
        return [[product.name, product.unit, "Activo" if product.active else "Inactivo"] for product in Product.select().limit(20)]
    except (InterfaceError, OperationalError):
        return []


def _driver_rows() -> list[list[str]]:
    try:
        return [
            [driver.name, driver.phone or "", "Disponible" if driver.available else "Ocupado"]
            for driver in Driver.select().limit(20)
        ]
    except (InterfaceError, OperationalError):
        return []


STYLES = """
QWidget { background: #f4f7fb; color: #111827; font-family: Arial; font-size: 14px; }
#topbar { background: #ffffff; border-bottom: 1px solid #e2e8f0; }
#appTitle { font-size: 24px; font-weight: 700; }
#sidebar { background: #f8fafc; border-right: 1px solid #e2e8f0; padding: 8px; }
#statusbar { background: #111827; color: #e5e7eb; }
#heading { font-size: 26px; font-weight: 700; margin-bottom: 12px; }
#card { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; min-height: 88px; }
#cardValue { font-size: 28px; font-weight: 700; }
QPushButton { background: #1d4ed8; color: #ffffff; border: 0; border-radius: 6px; padding: 10px 14px; }
QPushButton:disabled { background: #e2e8f0; color: #64748b; }
QTableWidget { background: #ffffff; gridline-color: #e2e8f0; border: 1px solid #cbd5e1; }
"""

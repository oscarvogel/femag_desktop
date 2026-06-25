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
    QHeaderView,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.database import bind_database, initialize_runtime_database
from app.models import ALL_MODELS
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.services.auth_service import AuthService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_workspace_spec
from app.ui.main_window import MainWindow as ShellBuilder


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
        database = SqliteDatabase(":memory:")
        bind_database(database)
        database.connect(reuse_if_open=True)
        database.create_tables(ALL_MODELS, safe=True)
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
        self._add_page(
            "carriers",
            self._table_page("Transportistas", ["Nombre", "CUIT", "Teléfono", "Estado"], _carrier_rows()),
        )
        self._add_page("load_orders", self._load_order_page())
        self._add_page("placeholder", self._placeholder_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(0)

    def _topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 10, 22, 10)
        layout.setSpacing(16)
        title = QLabel(self.shell.app_name)
        title.setObjectName("appTitle")
        search = QLineEdit()
        search.setObjectName("globalSearch")
        search.setPlaceholderText("Buscar en FEMAG...")
        search.setMinimumWidth(360)
        search.setMaximumWidth(520)
        notifications = QPushButton("Avisos")
        help_button = QPushButton("Ayuda")
        settings = QPushButton("Config")
        for button in (notifications, help_button, settings):
            button.setObjectName("topbarIconButton")
        user = QLabel(f"{self.shell.username}\n{self.shell.profile}")
        user.setObjectName("userBlock")
        user.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title)
        layout.addSpacing(30)
        layout.addWidget(search, 1)
        layout.addStretch(1)
        layout.addWidget(notifications)
        layout.addWidget(help_button)
        layout.addWidget(settings)
        layout.addWidget(user)
        return bar

    def _sidebar(self) -> QListWidget:
        self.nav.setObjectName("sidebar")
        self.nav.setFixedWidth(250)
        self.nav.setSpacing(4)
        for section in self.shell.sidebar.sections if self.shell.sidebar else []:
            for item in section.items:
                row = QListWidgetItem(item.title)
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
        layout.setContentsMargins(20, 6, 20, 6)
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
        page = _page(spec.title, "Vista general de actividad y accesos frecuentes")
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
        page = _page(title, "Listado maestro de consulta rápida")
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
        spec = build_load_order_workspace_spec()
        page = _page(spec.title, spec.subtitle)
        page.setObjectName("loadOrdersPage")
        layout = page.layout()
        service = LoadOrderService(current_user=self.shell.username)
        print_service = LoadOrderPrintService(current_user=self.shell.username)
        selected_order_id: dict[str, int | None] = {"value": None}

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(16)
        for index, (label, value, helper) in enumerate(_load_order_kpis(service)):
            kpi_grid.addWidget(_kpi_card(label, value, helper), 0, index)
        layout.addLayout(kpi_grid)

        feedback = QLabel("")
        feedback.setObjectName("loadOrderFeedback")

        workspace = QHBoxLayout()
        workspace.setSpacing(8)
        left_panel = QFrame()
        left_panel.setObjectName("contentPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        actions = QHBoxLayout()
        actions.setContentsMargins(10, 10, 10, 10)
        actions.setSpacing(8)
        new_button = _action_button("newLoadOrderButton", "Nuevo")
        add_client_button = _action_button("addLoadOrderClientButton", "Agregar cliente")
        remove_client_button = _action_button("removeLoadOrderClientButton", "Quitar cliente", secondary=True)
        add_product_button = _action_button("addLoadOrderProductButton", "Agregar producto")
        remove_product_button = _action_button("removeLoadOrderProductButton", "Quitar producto", secondary=True)
        save_button = _action_button("saveLoadOrderButton", "Guardar orden")
        edit_button = _action_button("editLoadOrderButton", "Editar", secondary=True)
        issue_button = _action_button("issueLoadOrderButton", "Emitir")
        annul_button = _action_button("annulLoadOrderButton", "Anular")
        print_button = _action_button("printLoadOrderButton", "Imprimir")
        search_button = _action_button("searchLoadOrderButton", "Buscar", secondary=True)
        for button in (
            new_button,
            add_client_button,
            remove_client_button,
            add_product_button,
            remove_product_button,
            save_button,
            issue_button,
            print_button,
            annul_button,
            search_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        left_layout.addLayout(actions)

        table = QTableWidget(0, len(spec.table_columns))
        table.setObjectName("loadOrdersTable")
        table.setHorizontalHeaderLabels(spec.table_columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        left_layout.addWidget(table, 1)
        left_layout.addWidget(feedback)

        detail = _detail_panel(spec)
        detail_labels: dict[str, QLabel] = detail.property("detailLabels")
        detail_actions = detail.property("detailActions")
        workspace.addWidget(left_panel, 1)
        workspace.addWidget(detail, 0)
        layout.addLayout(workspace, 1)

        def refresh() -> None:
            rows = service.list_orders() if hasattr(service, "list_orders") else []
            if not hasattr(service, "list_orders"):
                feedback.setText("Listado operativo pendiente de la capa funcional correspondiente.")
            table.setRowCount(len(rows))
            for row_index, order in enumerate(rows):
                values = (
                    _format_order_number(order.order_number),
                    order.date.strftime("%d/%m/%Y"),
                    _summarize_order_clients(order),
                    _summarize_order_deliveries(order),
                    _summarize_order_products(order),
                    str(sum(pallet.quantity for pallet in order.pallets)),
                    order.driver.name,
                    order.carrier.name,
                    _display_status(order.status),
                )
                for column, value in enumerate(values):
                    table.setItem(row_index, column, QTableWidgetItem(value))
                table.item(row_index, 0).setData(Qt.UserRole, order.id)
                table.item(row_index, 8).setForeground(_status_color(order.status))
            if rows and selected_order_id["value"] is None:
                table.setCurrentCell(0, 0)

        def clear_form() -> None:
            selected_order_id["value"] = None
            feedback.setText("Nuevo: use el flujo completo de orden en la próxima iteración funcional.")

        def selected_order() -> LoadOrder | None:
            if selected_order_id["value"] is None:
                return None
            return LoadOrder.get_by_id(selected_order_id["value"])

        def load_selected(row: int) -> None:
            if row < 0:
                return
            item = table.item(row, 0)
            if item is None:
                return
            order = LoadOrder.get_by_id(item.data(Qt.UserRole))
            selected_order_id["value"] = order.id
            first_product = order.products.first()
            first_pallet = order.pallets.first()
            detail_labels["number"].setText(_format_order_number(order.order_number))
            detail_labels["status"].setText(_display_status(order.status))
            detail_labels["status"].setObjectName(f"badge{_status_key(order.status)}")
            detail_labels["Fecha de orden"].setText(order.date.strftime("%d/%m/%Y"))
            detail_labels["Clientes / destinos"].setText(_order_destinations_text(order))
            detail_labels["Detalle de productos"].setText(_order_products_text(order))
            detail_labels["Cantidad (Pallets)"].setText(str(first_pallet.quantity if first_pallet else 0))
            detail_labels["Peso estimado"].setText(_estimated_weight(first_pallet))
            detail_labels["Chofer asignado"].setText(order.driver.name)
            detail_labels["Transportista"].setText(order.carrier.name)
            detail_labels["Camión / Acoplado"].setText(order.truck.domain)
            detail_labels["Observaciones"].setText(order.observations or "Sin observaciones.")

        def issue() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para emitir.")
                return
            try:
                service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida desde pantalla")
                feedback.setText(f"Orden {order.order_number} emitida.")
                selected_order_id["value"] = order.id
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
                selected_order_id["value"] = order.id
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
        add_client_button.clicked.connect(
            lambda: feedback.setText("Agregue un bloque de cliente/destino en el detalle de la carga.")
        )
        remove_client_button.clicked.connect(
            lambda: feedback.setText("Seleccione un bloque de cliente/destino para quitarlo de la carga.")
        )
        add_product_button.clicked.connect(
            lambda: feedback.setText("Agregue productos dentro del cliente/destino seleccionado.")
        )
        remove_product_button.clicked.connect(
            lambda: feedback.setText("Seleccione un producto del bloque actual para quitarlo.")
        )
        save_button.clicked.connect(
            lambda: feedback.setText("Guardar orden usa el detalle multi-cliente preparado para el alta funcional.")
        )
        edit_button.clicked.connect(lambda: feedback.setText("Editar: seleccione la orden y use el flujo completo."))
        detail_actions["edit"].clicked.connect(lambda: feedback.setText("Editar: seleccione la orden y use el flujo completo."))
        detail_actions["history"].clicked.connect(lambda: feedback.setText("Historial: disponible en auditoría de la orden."))
        search_button.clicked.connect(lambda: feedback.setText("Buscar: use el buscador global o filtre desde el listado."))
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


def _page(title: str, subtitle: str | None = None) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("heading")
    layout.addWidget(heading)
    if subtitle:
        subheading = QLabel(subtitle)
        subheading.setObjectName("subheading")
        layout.addWidget(subheading)
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


def _kpi_card(title: str, value: str, helper: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("kpiCard")
    layout = QVBoxLayout(frame)
    layout.addWidget(QLabel(title))
    value_label = QLabel(value)
    value_label.setObjectName("kpiValue")
    layout.addWidget(value_label)
    helper_label = QLabel(helper)
    helper_label.setObjectName("kpiHelper")
    layout.addWidget(helper_label)
    return frame


def _action_button(object_name: str, text: str, *, secondary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    if secondary:
        button.setProperty("secondary", True)
    return button


def _detail_panel(spec) -> QFrame:
    panel = QFrame()
    panel.setObjectName("detailPanel")
    panel.setFixedWidth(360)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(16, 16, 16, 12)
    title = QLabel("Detalle de la orden")
    title.setObjectName("detailTitle")
    number = QLabel("OC-000000")
    number.setObjectName("detailOrderNumber")
    status = QLabel("Pendiente")
    status.setObjectName("badgePendiente")
    layout.addWidget(title)
    layout.addWidget(number)
    layout.addWidget(status)
    labels = {"number": number, "status": status}
    for field in spec.detail_fields:
        label, value = _detail_row(field)
        layout.addWidget(label)
        layout.addWidget(value)
        labels[field] = value
    layout.addStretch(1)
    actions = QHBoxLayout()
    edit = _action_button("detailEditButton", "Editar")
    history = _action_button("detailHistoryButton", "Historial", secondary=True)
    actions.addWidget(edit)
    actions.addWidget(history)
    layout.addLayout(actions)
    panel.setProperty("detailLabels", labels)
    panel.setProperty("detailActions", {"edit": edit, "history": history})
    return panel


def _detail_row(label_text: str) -> tuple[QLabel, QLabel]:
    label = QLabel(label_text)
    label.setObjectName("detailLabel")
    value = QLabel("-")
    value.setObjectName("detailValue")
    value.setWordWrap(True)
    return label, value


def _load_order_kpis(service: LoadOrderService) -> list[tuple[str, str, str]]:
    try:
        issued_today = (
            LoadOrder.select()
            .where((LoadOrder.date == QDate.currentDate().toPyDate()) & (LoadOrder.status == LoadOrder.STATUS_ISSUED))
            .count()
        )
    except (InterfaceError, OperationalError):
        issued_today = 0
    return [
        ("Pendientes", str(service.pending_count()), "Órdenes sin emitir"),
        ("Emitidas hoy", str(issued_today), "Órdenes emitidas"),
        ("Camiones en carga", str(service.blocked_driver_count()), "En proceso"),
        ("Entregas del día", str(service.today_count()), "Programadas hoy"),
    ]


def _format_order_number(number: int) -> str:
    return f"OC-{number:06d}"


def _display_status(status: str) -> str:
    return {"Borrador": "Pendiente", "Cerrada": "Entregada"}.get(status, status)


def _status_key(status: str) -> str:
    return _display_status(status).replace(" ", "")


def _status_color(status: str):
    colors = {
        "Borrador": Qt.darkYellow,
        "Emitida": Qt.darkGreen,
        "Cerrada": Qt.darkGray,
        "Anulada": Qt.red,
    }
    return colors.get(status, Qt.blue)


def _estimated_weight(pallet) -> str:
    if pallet is None:
        return "-"
    return f"{pallet.weight * pallet.quantity:g} kg"


def _summarize_order_clients(order: LoadOrder) -> str:
    names = []
    for destination in order.destinations:
        if destination.client.name not in names:
            names.append(destination.client.name)
    if not names and order.client is not None:
        names.append(order.client.name)
    if len(names) > 1:
        return f"VARIOS ({len(names)})"
    return names[0] if names else ""


def _summarize_order_deliveries(order: LoadOrder) -> str:
    cities = []
    for destination in order.destinations:
        if destination.delivery_address.city not in cities:
            cities.append(destination.delivery_address.city)
    if not cities and order.delivery_address is not None:
        cities.append(order.delivery_address.city)
    return "; ".join(cities)


def _summarize_order_products(order: LoadOrder) -> str:
    products = list(order.products)
    if not products:
        return ""
    if len(products) == 1:
        return products[0].product.name
    return f"{len(products)} productos"


def _order_destinations_text(order: LoadOrder) -> str:
    parts = [
        f"{destination.client.name}: {destination.delivery_address.address}, {destination.delivery_address.city}"
        for destination in order.destinations
    ]
    if not parts and order.client is not None and order.delivery_address is not None:
        parts.append(f"{order.client.name}: {order.delivery_address.address}, {order.delivery_address.city}")
    return "\n".join(parts) or "-"


def _order_products_text(order: LoadOrder) -> str:
    parts = [
        f"{item.destination.client.name if item.destination else ''}: {item.product.name} x {item.quantity:g} {item.unit}"
        for item in order.products
    ]
    return "\n".join(parts) or "-"


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


def _carrier_rows() -> list[list[str]]:
    try:
        return [
            [carrier.name, carrier.cuit or "", carrier.phone or "", "Activo" if carrier.active else "Inactivo"]
            for carrier in Carrier.select().limit(20)
        ]
    except (InterfaceError, OperationalError):
        return []


STYLES = """
QWidget { background: #f6f8fb; color: #172033; font-family: Arial; font-size: 14px; }
#topbar { background: #ffffff; border-bottom: 1px solid #d9e1ec; min-height: 68px; }
#appTitle { font-size: 25px; font-weight: 700; color: #0f172a; }
#globalSearch { background: #ffffff; border: 1px solid #d9e1ec; border-radius: 8px; padding: 10px 14px; color: #334155; }
#topbarIconButton { background: #ffffff; color: #516174; border: 1px solid transparent; padding: 8px 10px; }
#topbarIconButton:hover { border: 1px solid #d9e1ec; background: #f8fafc; }
#userBlock { color: #172033; font-weight: 600; }
#sidebar { background: #ffffff; border-right: 1px solid #d9e1ec; padding: 12px; }
#sidebar::item { min-height: 38px; padding-left: 18px; border-radius: 6px; color: #334155; }
#sidebar::item:selected { background: #e8f1ff; color: #0b6fdc; border-left: 3px solid #0b6fdc; font-weight: 700; }
#sidebar::item:disabled { color: #94a3b8; }
#statusbar { background: #ffffff; color: #64748b; border-top: 1px solid #d9e1ec; }
#heading { font-size: 25px; font-weight: 700; margin-bottom: 0; color: #111827; }
#subheading { color: #526174; margin-bottom: 6px; }
#card, #kpiCard, #contentPanel, #detailPanel { background: #ffffff; border: 1px solid #d9e1ec; border-radius: 8px; }
#card { min-height: 88px; }
#cardValue, #kpiValue { font-size: 28px; font-weight: 700; color: #111827; }
#kpiCard { min-height: 96px; }
#kpiHelper { color: #64748b; font-size: 12px; }
#detailPanel { margin-left: 8px; }
#detailTitle { font-size: 16px; font-weight: 700; color: #111827; }
#detailOrderNumber { color: #0b6fdc; font-size: 20px; font-weight: 700; margin-top: 6px; }
#detailLabel { color: #64748b; font-size: 12px; margin-top: 7px; }
#detailValue { color: #172033; font-size: 13px; }
#badgePendiente, #badgeEmitida, #badgeEncarga, #badgeEntregada, #badgeAnulada {
    border-radius: 8px; padding: 4px 8px; font-weight: 700; max-width: 120px;
}
#badgePendiente { background: #fff7d6; color: #b45309; border: 1px solid #f6c453; }
#badgeEmitida { background: #dcfce7; color: #15803d; border: 1px solid #86efac; }
#badgeEncarga { background: #dbeafe; color: #0b6fdc; border: 1px solid #93c5fd; }
#badgeEntregada { background: #e5e7eb; color: #475569; border: 1px solid #cbd5e1; }
#badgeAnulada { background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; }
QPushButton { background: #0b6fdc; color: #ffffff; border: 0; border-radius: 6px; padding: 9px 14px; font-weight: 600; }
QPushButton[secondary="true"] { background: #ffffff; color: #334155; border: 1px solid #d9e1ec; }
QPushButton:disabled { background: #e2e8f0; color: #64748b; }
QTableWidget { background: #ffffff; alternate-background-color: #fbfdff; gridline-color: #edf2f7; border: 0; selection-background-color: #e8f1ff; selection-color: #0f172a; }
QHeaderView::section { background: #ffffff; color: #334155; border: 0; border-bottom: 1px solid #d9e1ec; padding: 10px; font-weight: 700; }
"""

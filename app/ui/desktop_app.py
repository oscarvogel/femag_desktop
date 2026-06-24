from __future__ import annotations

from peewee import InterfaceError, OperationalError, SqliteDatabase
from PyQt5.QtCore import QDate, QTimer, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
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
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import (
    build_load_order_screen_state,
    build_load_order_workspace_spec,
    create_load_order_from_screen,
)
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
        _seed_demo_operational_data()
        return database
    try:
        database = initialize_runtime_database()
        database.connect(reuse_if_open=True)
        return database
    except Exception:
        return None


def _seed_demo_operational_data() -> None:
    client = Client.create(name="FEMAG Demo", cuit="30700000001", iva_condition="RI")
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
        is_primary=True,
    )
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Parque Industrial",
    )
    carrier = Carrier.create(name="Transporte Norte Demo", cuit="30700000002")
    Truck.create(domain="AB123CD", carrier=carrier)
    Truck.create(domain="AC456EF", carrier=carrier)
    Driver.create(name="Juan Perez", carrier=carrier)
    Driver.create(name="Maria Gomez", carrier=carrier)
    Product.create(name="Fecula de mandioca", unit="kg")
    Product.create(name="Almidon", unit="kg")
    PalletType.create(type="Pallet comun", measure="1x1", weight=12.5)


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
        self.nav.setFocus()
        QTimer.singleShot(0, self.nav.setFocus)

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
        search.setFocusPolicy(Qt.ClickFocus)
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
        selected_order_id: dict[str, int | None] = {"value": None}

        kpi_grid = QGridLayout()
        kpi_grid.setSpacing(16)
        for index, (label, value, helper) in enumerate(_load_order_kpis(service)):
            kpi_grid.addWidget(_kpi_card(label, value, helper), index // 2, index % 2)
        layout.addLayout(kpi_grid)

        feedback = QLabel("")
        feedback.setObjectName("loadOrderFeedback")

        filters = QHBoxLayout()
        filters.setSpacing(8)
        date_filter = QDateEdit()
        date_filter.setObjectName("loadOrderDateFilter")
        date_filter.setCalendarPopup(True)
        date_filter.setDisplayFormat("dd/MM/yyyy")
        date_filter.setSpecialValueText("")
        date_filter.setDate(QDate.currentDate())
        client_filter = QComboBox()
        client_filter.setObjectName("loadOrderClientFilter")
        status_filter = QComboBox()
        status_filter.setObjectName("loadOrderStatusFilter")
        filter_button = _action_button("filterLoadOrdersButton", "Buscar", secondary=True)
        clear_filter_button = _action_button("clearLoadOrderFiltersButton", "Limpiar", secondary=True)
        filters.addWidget(QLabel("Fecha"))
        filters.addWidget(date_filter)
        filters.addWidget(QLabel("Cliente"))
        filters.addWidget(client_filter, 1)
        filters.addWidget(QLabel("Estado"))
        filters.addWidget(status_filter)
        filters.addWidget(filter_button)
        filters.addWidget(clear_filter_button)
        layout.addLayout(filters)

        workspace = QVBoxLayout()
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
        issue_button = _action_button("issueLoadOrderButton", "Emitir")
        annul_button = _action_button("annulLoadOrderButton", "Anular")
        for button in (new_button, issue_button, annul_button):
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

        form_panel = QFrame()
        form_panel.setObjectName("detailPanel")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(16, 16, 16, 12)
        form_title = QLabel("Nueva orden")
        form_title.setObjectName("detailTitle")
        form_layout.addWidget(form_title)
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        order_date = QDateEdit()
        order_date.setObjectName("loadOrderDateInput")
        order_date.setCalendarPopup(True)
        order_date.setDisplayFormat("dd/MM/yyyy")
        order_date.setDate(QDate.currentDate())
        client_combo = QComboBox()
        client_combo.setObjectName("loadOrderClientInput")
        address_combo = QComboBox()
        address_combo.setObjectName("loadOrderAddressInput")
        carrier_combo = QComboBox()
        carrier_combo.setObjectName("loadOrderCarrierInput")
        truck_combo = QComboBox()
        truck_combo.setObjectName("loadOrderTruckInput")
        driver_combo = QComboBox()
        driver_combo.setObjectName("loadOrderDriverInput")
        product_combo = QComboBox()
        product_combo.setObjectName("loadOrderProductInput")
        quantity_input = QDoubleSpinBox()
        quantity_input.setObjectName("loadOrderQuantityInput")
        quantity_input.setRange(0, 999999)
        quantity_input.setDecimals(2)
        quantity_input.setSuffix(" kg")
        observations_input = QLineEdit()
        observations_input.setObjectName("loadOrderObservationsInput")
        for field in (
            order_date,
            client_combo,
            address_combo,
            carrier_combo,
            truck_combo,
            driver_combo,
            product_combo,
        ):
            field.setMaximumWidth(230)
        quantity_input.setMaximumWidth(160)
        observations_input.setMaximumWidth(360)
        form.addWidget(QLabel("Fecha"), 0, 0)
        form.addWidget(order_date, 0, 1)
        form.addWidget(QLabel("Transportista"), 0, 2)
        form.addWidget(carrier_combo, 0, 3)
        form.addWidget(QLabel("Cliente"), 1, 0)
        form.addWidget(client_combo, 1, 1)
        form.addWidget(QLabel("Camión"), 1, 2)
        form.addWidget(truck_combo, 1, 3)
        form.addWidget(QLabel("Domicilio entrega"), 2, 0)
        form.addWidget(address_combo, 2, 1)
        form.addWidget(QLabel("Chofer"), 2, 2)
        form.addWidget(driver_combo, 2, 3)
        form.addWidget(QLabel("Producto"), 3, 0)
        form.addWidget(product_combo, 3, 1)
        form.addWidget(QLabel("Cantidad"), 3, 2)
        form.addWidget(quantity_input, 3, 3)
        form.addWidget(QLabel("Observaciones"), 4, 0)
        form.addWidget(observations_input, 4, 1, 1, 2)
        save_button = _action_button("saveLoadOrderButton", "Guardar orden")
        form_layout.addLayout(form)
        form_layout.addWidget(save_button)
        form_layout.addStretch(1)
        workspace.addWidget(form_panel, 0)
        workspace.addWidget(left_panel, 1)
        layout.addLayout(workspace, 1)

        def load_state(*, keep_filters: bool = True):
            client_filter_id = _combo_data(client_filter) if keep_filters else None
            status = status_filter.currentData() if keep_filters else None
            day = date_filter.date().toPyDate() if keep_filters else None
            return build_load_order_screen_state(
                current_user=self.shell.username,
                selected_client_id=_combo_data(client_combo),
                selected_carrier_id=_combo_data(carrier_combo),
                selected_truck_id=_combo_data(truck_combo),
                filter_client_id=client_filter_id,
                filter_status=status,
                filter_date=day,
            )

        def populate_filters() -> None:
            state = build_load_order_screen_state(current_user=self.shell.username)
            _fill_combo(client_filter, state.clients, include_empty=True)
            _fill_text_combo(status_filter, state.statuses)

        def populate_form_options() -> None:
            selected_client = _combo_data(client_combo)
            selected_address = _combo_data(address_combo)
            selected_carrier = _combo_data(carrier_combo)
            selected_truck = _combo_data(truck_combo)
            selected_driver = _combo_data(driver_combo)
            selected_product = _combo_data(product_combo)
            state = load_state(keep_filters=False)
            _fill_combo(client_combo, state.clients, include_empty=True, selected=selected_client)
            _fill_combo(address_combo, state.delivery_addresses, include_empty=True, selected=selected_address)
            _fill_combo(carrier_combo, state.carriers, include_empty=True, selected=selected_carrier)
            _fill_combo(truck_combo, state.trucks, include_empty=True, selected=selected_truck)
            _fill_combo(driver_combo, state.drivers, include_empty=True, selected=selected_driver)
            _fill_combo(product_combo, state.products, include_empty=True, selected=selected_product)

        def refresh() -> None:
            state = load_state()
            rows = state.rows
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                values = (
                    row.number,
                    row.date,
                    row.client,
                    row.delivery,
                    row.product,
                    row.quantity,
                    row.driver,
                    row.carrier,
                    row.status,
                )
                for column, value in enumerate(values):
                    table.setItem(row_index, column, QTableWidgetItem(value))
                table.item(row_index, 0).setData(Qt.UserRole, row.id)
                table.item(row_index, 8).setForeground(_status_color(row.status))
            if rows and selected_order_id["value"] is None:
                table.setCurrentCell(0, 0)
            if not rows:
                feedback.setText(state.empty_message)
            elif not feedback.text():
                feedback.setText(f"{len(rows)} orden(es) en pantalla.")

        def clear_form() -> None:
            selected_order_id["value"] = None
            form_title.setText("Nueva orden")
            order_date.setDate(QDate.currentDate())
            quantity_input.setValue(0)
            observations_input.clear()
            populate_form_options()
            feedback.setText("Complete los datos obligatorios y guarde la orden.")

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
            form_title.setText(f"Orden {_format_order_number(order.order_number)}")
            feedback.setText(f"Orden seleccionada: {_format_order_number(order.order_number)}.")

        def save() -> None:
            try:
                order = create_load_order_from_screen(
                    current_user=self.shell.username,
                    client_id=_combo_data(client_combo),
                    delivery_address_id=_combo_data(address_combo),
                    carrier_id=_combo_data(carrier_combo),
                    truck_id=_combo_data(truck_combo),
                    driver_id=_combo_data(driver_combo),
                    product_id=_combo_data(product_combo),
                    quantity=quantity_input.value(),
                    observations=observations_input.text().strip() or None,
                    order_date=order_date.date().toPyDate(),
                )
                selected_order_id["value"] = order.id
                feedback.setText(f"Orden {_format_order_number(order.order_number)} guardada.")
                populate_filters()
                populate_form_options()
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

        table.currentCellChanged.connect(lambda row, _column, _previous_row, _previous_column: load_selected(row))
        client_combo.currentIndexChanged.connect(lambda _index: populate_form_options())
        carrier_combo.currentIndexChanged.connect(lambda _index: populate_form_options())
        truck_combo.currentIndexChanged.connect(lambda _index: populate_form_options())
        new_button.clicked.connect(clear_form)
        save_button.clicked.connect(save)
        filter_button.clicked.connect(refresh)
        clear_filter_button.clicked.connect(lambda: (populate_filters(), refresh()))
        issue_button.clicked.connect(issue)
        annul_button.clicked.connect(annul)
        populate_filters()
        populate_form_options()
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


def _combo_data(combo: QComboBox):
    return combo.currentData()


def _fill_combo(combo: QComboBox, options, *, include_empty: bool = False, selected=None) -> None:
    previous = selected if selected is not None else combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    if include_empty:
        combo.addItem("", None)
    for option in options:
        combo.addItem(option.label, option.id)
    index = combo.findData(previous)
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.count() > 0:
        combo.setCurrentIndex(0)
    combo.blockSignals(False)


def _fill_text_combo(combo: QComboBox, values: tuple[str, ...]) -> None:
    previous = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for value in values:
        combo.addItem(value, value or None)
    index = combo.findData(previous)
    if index >= 0:
        combo.setCurrentIndex(index)
    combo.blockSignals(False)


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

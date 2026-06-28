from __future__ import annotations

import os
from pathlib import Path
import webbrowser

from peewee import InterfaceError, OperationalError
from PyQt5.QtCore import QDate, QSignalBlocker, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
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
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.database import initialize_demo_database, initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.services.auth_service import AuthService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_workspace_spec
from app.ui.main_window import MainWindow as ShellBuilder
from app.ui.master_abm import build_master_abm_page, master_abm_configs


LOAD_ORDER_PRINTS_DIR = Path("docs") / "prints"


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
        database = initialize_demo_database()
        database.connect(reuse_if_open=True)
        ensure_runtime_schema(database)
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
        self.user = user
        self.shell = ShellBuilder(user=user, demo_mode=demo_mode).shell_spec
        self.setWindowTitle("FEMAG Desktop")
        self.resize(1280, 820)
        self.setStyleSheet(STYLES)
        self.stack = QStackedWidget()
        self.nav = QListWidget()
        self._route_indexes: dict[str, int] = {}
        self._expanded_sidebar_groups: set[str] = set()
        self._current_route = "dashboard"
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
        self._add_master_pages()
        self._add_page("load_orders", self._load_order_page())
        self._add_page("placeholder", self._placeholder_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(0)

    def _add_master_pages(self) -> None:
        for route, config in master_abm_configs().items():
            self._add_page(
                route,
                build_master_abm_page(
                    config=config,
                    user=self.user,
                    current_user=self.shell.username,
                    parent=self,
                ),
            )

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
        self._populate_sidebar()
        return self.nav

    def _populate_sidebar(self) -> None:
        with QSignalBlocker(self.nav):
            self.nav.clear()
            current_row = 0
            for section in self.shell.sidebar.sections if self.shell.sidebar else []:
                for item in section.items:
                    row_index = self.nav.count()
                    row = QListWidgetItem(item.title)
                    if item.children:
                        group_key = f"group:{item.title}"
                        row.setData(Qt.UserRole, group_key)
                        row.setToolTip("Mostrar u ocultar ABMs relacionados.")
                        self.nav.addItem(row)
                        child_routes = {child.route_key for child in item.children}
                        if self._current_route in child_routes:
                            self._expanded_sidebar_groups.add(item.title)
                        if item.title in self._expanded_sidebar_groups:
                            for child in item.children:
                                child_row_index = self.nav.count()
                                child_row = QListWidgetItem(f"    {child.title}")
                                route = child.route_key or "placeholder"
                                child_row.setData(Qt.UserRole, route)
                                if child.placeholder:
                                    child_row.setForeground(Qt.gray)
                                    child_row.setToolTip(child.disabled_reason or future_module_message())
                                self.nav.addItem(child_row)
                                if route == self._current_route:
                                    current_row = child_row_index
                        continue
                    route = item.route_key or "placeholder"
                    row.setData(Qt.UserRole, route)
                    if item.placeholder:
                        row.setForeground(Qt.gray)
                        row.setToolTip(item.disabled_reason or future_module_message())
                    self.nav.addItem(row)
                    if route == self._current_route:
                        current_row = row_index
            if self.nav.count():
                self.nav.setCurrentRow(current_row)

    def _toggle_sidebar_group(self, group_title: str) -> None:
        if group_title in self._expanded_sidebar_groups:
            self._expanded_sidebar_groups.remove(group_title)
        else:
            self._expanded_sidebar_groups.add(group_title)
        self._populate_sidebar()

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
        if isinstance(route, str) and route.startswith("group:"):
            self._toggle_sidebar_group(route.removeprefix("group:"))
            return
        if route in self._route_indexes:
            self._current_route = route
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
        operation_service = LoadOrderOperationService(
            current_user=self.shell.username,
            prints_dir=LOAD_ORDER_PRINTS_DIR,
        )
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
        edit_button = _action_button("editLoadOrderButton", "Editar", secondary=True)
        issue_button = _action_button("issueLoadOrderButton", "Emitir")
        close_button = _action_button("closeLoadOrderButton", "Cerrar")
        annul_button = _action_button("annulLoadOrderButton", "Anular")
        print_button = _action_button("printLoadOrderButton", "Imprimir")
        search_input = QLineEdit()
        search_input.setObjectName("loadOrderSearchInput")
        search_input.setPlaceholderText("Buscar orden, cliente, destino, producto, chofer...")
        search_input.setMinimumWidth(260)
        search_button = _action_button("searchLoadOrderButton", "Buscar", secondary=True)
        for button in (new_button, edit_button, issue_button, close_button, print_button, annul_button):
            actions.addWidget(button)
        actions.addWidget(search_input)
        actions.addWidget(search_button)
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
        workspace.addWidget(left_panel, 1)
        workspace.addWidget(detail, 0)
        layout.addLayout(workspace, 1)

        def refresh(*, query: str | None = None) -> None:
            rows = service.list_orders() if hasattr(service, "list_orders") else []
            if not hasattr(service, "list_orders"):
                feedback.setText("Listado operativo pendiente de la capa funcional correspondiente.")
            query = (query if query is not None else search_input.text()).strip()
            if query:
                rows = [order for order in rows if _matches_load_order_query(order, query)]
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
                    order.truck.domain,
                    _display_status(order.status),
                )
                for column, value in enumerate(values):
                    table.setItem(row_index, column, QTableWidgetItem(value))
                table.item(row_index, 0).setData(Qt.UserRole, order.id)
                table.item(row_index, 9).setForeground(_status_color(order.status))
            if rows:
                selected_row = 0
                if selected_order_id["value"] is not None:
                    for row_index in range(table.rowCount()):
                        item = table.item(row_index, 0)
                        if item is not None and item.data(Qt.UserRole) == selected_order_id["value"]:
                            selected_row = row_index
                            break
                table.setCurrentCell(selected_row, 0)
                load_selected(selected_row)
            else:
                selected_order_id["value"] = None
                clear_detail()

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
            first_pallet = order.pallets.first()
            detail_labels["number"].setText(_format_order_number(order.order_number))
            detail_labels["status"].setText(_display_status(order.status))
            detail_labels["status"].setProperty("statusKey", _status_key(order.status))
            detail_labels["Fecha de orden"].setText(order.date.strftime("%d/%m/%Y"))
            detail_labels["Clientes / destinos"].setText(_order_destinations_text(order))
            detail_labels["Detalle de productos"].setText(_order_products_text(order))
            detail_labels["Cantidad (Pallets)"].setText(str(first_pallet.quantity if first_pallet else 0))
            detail_labels["Peso estimado"].setText(_estimated_weight(first_pallet))
            detail_labels["Chofer asignado"].setText(order.driver.name)
            detail_labels["Transportista"].setText(order.carrier.name)
            detail_labels["Camión / Acoplado"].setText(order.truck.domain)
            detail_labels["Observaciones"].setText(order.observations or "Sin observaciones.")
            set_action_state(order)

        def clear_detail() -> None:
            detail_labels["number"].setText("OC-000000")
            detail_labels["status"].setText("-")
            for field in spec.detail_fields:
                detail_labels[field].setText("-")
            issue_button.setEnabled(False)
            issue_button.setToolTip("Seleccione una orden pendiente para emitir.")
            edit_button.setEnabled(False)
            edit_button.setToolTip("Seleccione una orden pendiente para editar.")
            close_button.setEnabled(False)
            close_button.setToolTip("Seleccione una orden emitida para cerrar.")

        def set_action_state(order: LoadOrder) -> None:
            is_pending = order.status == LoadOrder.STATUS_PENDING
            is_issued = order.status == LoadOrder.STATUS_ISSUED
            issue_button.setEnabled(is_pending)
            edit_button.setEnabled(is_pending)
            close_button.setEnabled(is_issued)
            if is_pending:
                issue_button.setToolTip("Emitir la orden seleccionada.")
                edit_button.setToolTip("Editar la orden pendiente seleccionada.")
                close_button.setToolTip("Primero emita la orden para poder cerrarla.")
            elif order.status == LoadOrder.STATUS_ISSUED:
                issue_button.setToolTip("La orden ya esta emitida.")
                edit_button.setToolTip("Solo se pueden editar ordenes pendientes.")
                close_button.setToolTip("Cerrar la orden y liberar el chofer si no tiene otra carga activa.")
            else:
                issue_button.setToolTip("Solo se pueden emitir ordenes pendientes.")
                edit_button.setToolTip("Solo se pueden editar ordenes pendientes.")
                close_button.setToolTip("Solo se pueden cerrar ordenes emitidas.")

        def open_new_order_dialog() -> None:
            dialog = LoadOrderEntryDialog(service, self.shell.username, self)
            if dialog.exec_() == QDialog.Accepted and dialog.created_order is not None:
                selected_order_id["value"] = dialog.created_order.id
                refresh()
                feedback.setText(f"Orden {_format_order_number(dialog.created_order.order_number)} guardada.")

        def open_edit_order_dialog() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para editar.")
                return
            if order.status != LoadOrder.STATUS_PENDING:
                feedback.setText("Solo se pueden editar ordenes pendientes.")
                return
            dialog = LoadOrderEntryDialog(service, self.shell.username, self, order=order)
            if dialog.exec_() == QDialog.Accepted and dialog.created_order is not None:
                selected_order_id["value"] = dialog.created_order.id
                refresh()
                feedback.setText(f"Orden {_format_order_number(dialog.created_order.order_number)} actualizada.")

        def issue() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para emitir.")
                return
            try:
                issued = operation_service.issue(order)
                feedback.setText(f"Orden {_format_order_number(issued.order_number)} emitida.")
                selected_order_id["value"] = issued.id
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def annul() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para anular.")
                return
            try:
                annulled = operation_service.annul(order, can_annul=_can_annul_load_orders(self.user))
                feedback.setText(f"Orden {_format_order_number(annulled.order_number)} anulada.")
                selected_order_id["value"] = annulled.id
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def close_order() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para cerrar.")
                return
            if order.status != LoadOrder.STATUS_ISSUED:
                feedback.setText("Solo se pueden cerrar ordenes emitidas.")
                return
            try:
                closed = service.change_status(order, LoadOrder.STATUS_CLOSED, reason="Cierre operativo")
                feedback.setText(f"Orden {_format_order_number(closed.order_number)} cerrada.")
                selected_order_id["value"] = closed.id
                refresh()
            except Exception as exc:
                feedback.setText(str(exc))

        def print_or_reprint_order() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para imprimir.")
                return
            try:
                if _has_printed_load_order(order):
                    path = operation_service.reprint_order(order)
                    _open_print_output(path)
                    feedback.setText(f"Reimpresion A4 generada: {path}")
                else:
                    path = operation_service.print_order(order)
                    _open_print_output(path)
                    feedback.setText(f"Vista A4 generada: {path}")
            except Exception as exc:
                feedback.setText(str(exc))

        def search_orders() -> None:
            query = search_input.text().strip()
            refresh(query=query)
            count = table.rowCount()
            if query:
                feedback.setText(f"Buscar '{query}': {count} resultado(s).")
            else:
                feedback.setText(f"Buscar: {count} orden(es).")

        table.currentCellChanged.connect(lambda row, _column, _previous_row, _previous_column: load_selected(row))
        new_button.clicked.connect(open_new_order_dialog)
        edit_button.clicked.connect(open_edit_order_dialog)
        search_button.clicked.connect(search_orders)
        search_input.returnPressed.connect(search_orders)
        issue_button.clicked.connect(issue)
        close_button.clicked.connect(close_order)
        annul_button.clicked.connect(annul)
        print_button.clicked.connect(print_or_reprint_order)
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
    status.setObjectName("detailOrderStatus")
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
    panel.setProperty("detailLabels", labels)
    return panel


class LoadOrderEntryDialog(QDialog):
    def __init__(self, service: LoadOrderService, current_user: str, parent=None, *, order: LoadOrder | None = None):
        super().__init__(parent)
        self.service = service
        self.current_user = current_user
        self.order = LoadOrder.get_by_id(order.id) if order is not None else None
        self.created_order: LoadOrder | None = None
        self.destinations: list[dict] = []
        self.setObjectName("loadOrderEntryDialog")
        self.setWindowTitle("Editar orden de carga" if self.order is not None else "Nueva orden de carga")
        self.setMinimumSize(980, 760)
        self.resize(1100, 820)
        self._build()
        self._populate_options()
        self._load_order()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)
        title = QLabel("Editar orden de carga" if self.order is not None else "Nueva orden de carga")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        hint = QLabel("Seleccione el chofer. El transportista se cargara automaticamente. Luego elija camion y complete los destinos.")
        hint.setObjectName("formHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("loadOrderEntryScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("formSection")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 12)
        header_layout.setHorizontalSpacing(10)
        header_layout.setVerticalSpacing(8)
        self.order_date = QDateEdit()
        self.order_date.setObjectName("loadOrderDateInput")
        self.order_date.setCalendarPopup(True)
        self.order_date.setDisplayFormat("dd/MM/yyyy")
        self.order_date.setDate(QDate.currentDate())
        self.carrier_combo = QComboBox()
        self.carrier_combo.setObjectName("loadOrderCarrierInput")
        self.truck_combo = QComboBox()
        self.truck_combo.setObjectName("loadOrderTruckInput")
        self.driver_combo = QComboBox()
        self.driver_combo.setObjectName("loadOrderDriverInput")
        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("loadOrderObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones generales")
        header_layout.addWidget(QLabel("Fecha"), 0, 0)
        header_layout.addWidget(self.order_date, 0, 1)
        header_layout.addWidget(QLabel("Chofer"), 0, 2)
        header_layout.addWidget(self.driver_combo, 0, 3)
        header_layout.addWidget(QLabel("Transportista"), 1, 0)
        header_layout.addWidget(self.carrier_combo, 1, 1)
        header_layout.addWidget(QLabel("Camion / patente"), 1, 2)
        header_layout.addWidget(self.truck_combo, 1, 3)
        header_layout.addWidget(QLabel("Observaciones"), 2, 0)
        header_layout.addWidget(self.observations_input, 2, 1, 1, 3)
        content_layout.addWidget(header)

        work_splitter = QSplitter(Qt.Vertical)
        work_splitter.setObjectName("loadOrderEntryWorkSplitter")
        work_splitter.setChildrenCollapsible(False)
        work_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        destination = QFrame()
        destination.setObjectName("formSection")
        destination_layout = QVBoxLayout(destination)
        destination_layout.setContentsMargins(12, 12, 12, 12)
        destination_layout.setSpacing(8)
        destination_title = QLabel("Clientes y destinos")
        destination_title.setObjectName("sectionTitle")
        destination_layout.addWidget(destination_title)
        destination_inputs = QGridLayout()
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("loadOrderClientInput")
        self.address_combo = QComboBox()
        self.address_combo.setObjectName("loadOrderAddressInput")
        add_destination_button = _action_button("addLoadOrderClientButton", "Agregar cliente/destino")
        remove_destination_button = _action_button("removeLoadOrderClientButton", "Quitar seleccionado", secondary=True)
        destination_inputs.addWidget(QLabel("Cliente"), 0, 0)
        destination_inputs.addWidget(self.client_combo, 0, 1)
        destination_inputs.addWidget(QLabel("Destino"), 1, 0)
        destination_inputs.addWidget(self.address_combo, 1, 1)
        destination_inputs.addWidget(add_destination_button, 2, 0)
        destination_inputs.addWidget(remove_destination_button, 2, 1)
        destination_layout.addLayout(destination_inputs)
        self.destination_table = QTableWidget(0, 3)
        self.destination_table.setObjectName("loadOrderDestinationDraftTable")
        self.destination_table.setHorizontalHeaderLabels(("Cliente", "Destino", "Productos"))
        self.destination_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.destination_table.verticalHeader().setVisible(False)
        self.destination_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.destination_table.setMinimumHeight(180)
        destination_layout.addWidget(self.destination_table)
        work_splitter.addWidget(destination)

        product = QFrame()
        product.setObjectName("formSection")
        product_layout = QVBoxLayout(product)
        product_layout.setContentsMargins(12, 12, 12, 12)
        product_layout.setSpacing(8)
        product_title = QLabel("Productos del cliente/destino seleccionado")
        product_title.setObjectName("sectionTitle")
        product_layout.addWidget(product_title)
        product_actions = QHBoxLayout()
        add_product_button = _action_button("addLoadOrderProductButton", "Agregar producto")
        remove_product_button = _action_button("removeLoadOrderProductButton", "Quitar producto", secondary=True)
        product_actions.addWidget(add_product_button)
        product_actions.addWidget(remove_product_button)
        product_actions.addStretch(1)
        product_layout.addLayout(product_actions)
        self.product_table = QTableWidget(0, 3)
        self.product_table.setObjectName("loadOrderProductDraftTable")
        self.product_table.setHorizontalHeaderLabels(("Producto", "Cantidad", "Unidad"))
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.product_table.setMinimumHeight(160)
        product_layout.addWidget(self.product_table)
        work_splitter.addWidget(product)
        work_splitter.setStretchFactor(0, 3)
        work_splitter.setStretchFactor(1, 2)
        content_layout.addWidget(work_splitter, 1)
        scroll_area.setWidget(content)
        root.addWidget(scroll_area, 1)

        self.feedback = QLabel("")
        self.feedback.setObjectName("loadOrderDialogFeedback")
        self.feedback.setWordWrap(True)
        root.addWidget(self.feedback)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_button = _action_button("cancelLoadOrderButton", "Cancelar", secondary=True)
        save_button = _action_button("saveLoadOrderButton", "Guardar orden")
        footer.addWidget(cancel_button)
        footer.addWidget(save_button)
        root.addLayout(footer)

        add_destination_button.clicked.connect(self._add_destination)
        remove_destination_button.clicked.connect(self._remove_destination)
        add_product_button.clicked.connect(self._open_product_dialog)
        remove_product_button.clicked.connect(self._remove_product)
        save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        self.destination_table.currentCellChanged.connect(
            lambda row, _column, _previous_row, _previous_column: self._render_products(row)
        )
        self.driver_combo.currentIndexChanged.connect(lambda _index: self._refresh_from_driver())
        self.client_combo.currentIndexChanged.connect(lambda _index: self._refresh_address_options())

    def _populate_options(self) -> None:
        _fill_combo(self.driver_combo, _driver_options())
        _fill_combo(self.carrier_combo, _carrier_options())
        self.carrier_combo.setEnabled(False)
        _fill_combo(self.client_combo, _client_options())
        self._refresh_address_options()

    def _load_order(self) -> None:
        if self.order is None:
            return
        self.order_date.setDate(QDate(self.order.date.year, self.order.date.month, self.order.date.day))
        _set_combo(self.driver_combo, self.order.driver.id)
        self._refresh_from_driver()
        _set_combo(self.truck_combo, self.order.truck.id)
        self.observations_input.setText(self.order.observations or "")
        self.destinations = [
            {
                "client_id": destination.client.id,
                "address_id": destination.delivery_address.id,
                "client_label": destination.client.name,
                "address_label": f"{destination.delivery_address.client.name} - {destination.delivery_address.address}, {destination.delivery_address.city}",
                "products": [
                    {
                        "product_id": product.product.id,
                        "product_label": product.product.name,
                        "quantity": product.quantity,
                        "unit": product.unit,
                    }
                    for product in destination.products
                ],
            }
            for destination in self.order.destinations.order_by()
        ]
        self._render_destinations()

    def _refresh_from_driver(self) -> None:
        driver_id = self.driver_combo.currentData()
        if driver_id is None:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            return
        try:
            driver = Driver.get_by_id(driver_id)
        except Driver.DoesNotExist:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            return
        try:
            carrier = driver.carrier
        except Carrier.DoesNotExist:
            carrier = None
        if carrier is None:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            return
        carrier_id = carrier.id
        if self.carrier_combo.findData(carrier_id) < 0:
            _fill_combo(self.carrier_combo, _carrier_options())
        _set_combo(self.carrier_combo, carrier_id)
        _fill_combo(self.truck_combo, _truck_options(carrier_id=carrier_id))
        if self.truck_combo.count() == 1:
            self.truck_combo.setCurrentIndex(0)

    def _refresh_address_options(self) -> None:
        client_id = self.client_combo.currentData()
        options = _address_options(client_id=client_id)
        _fill_combo(self.address_combo, options)
        if len(options) == 1:
            self.address_combo.setCurrentIndex(1)
        if client_id is not None and not options:
            self.feedback.setText("El cliente seleccionado no tiene lugares de entrega activos.")

    def _add_destination(self) -> None:
        client_id = self.client_combo.currentData()
        address_id = self.address_combo.currentData()
        if client_id is None or address_id is None:
            self.feedback.setText("Seleccione cliente y destino.")
            return
        address = ClientAddress.get_by_id(address_id)
        if address.client.id != client_id:
            self.feedback.setText("El destino seleccionado no pertenece al cliente.")
            return
        self.destinations.append(
            {
                "client_id": client_id,
                "address_id": address_id,
                "client_label": self.client_combo.currentText(),
                "address_label": self.address_combo.currentText(),
                "products": [],
            }
        )
        self._render_destinations()
        self.feedback.setText("Cliente/destino agregado. Ahora agregue productos.")

    def _remove_destination(self) -> None:
        row = self.destination_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            self.feedback.setText("Seleccione un cliente/destino.")
            return
        self.destinations.pop(row)
        self._render_destinations()
        self.feedback.setText("Cliente/destino quitado.")

    def _open_product_dialog(self) -> None:
        row = self.destination_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            self.feedback.setText("Seleccione un cliente/destino antes de agregar productos.")
            return
        dialog = LoadOrderProductDialog(self)
        if dialog.exec_() != QDialog.Accepted or dialog.product is None:
            return
        self.destinations[row]["products"].append(dialog.product)
        self._render_products(row)
        self._render_destinations()
        self.destination_table.setCurrentCell(row, 0)
        self.feedback.setText("Producto agregado.")

    def _remove_product(self) -> None:
        destination_row = self.destination_table.currentRow()
        product_row = self.product_table.currentRow()
        if destination_row < 0 or destination_row >= len(self.destinations):
            self.feedback.setText("Seleccione un cliente/destino.")
            return
        products = self.destinations[destination_row]["products"]
        if product_row < 0 or product_row >= len(products):
            self.feedback.setText("Seleccione un producto.")
            return
        products.pop(product_row)
        self._render_products(destination_row)
        self._render_destinations()
        self.destination_table.setCurrentCell(destination_row, 0)
        self.feedback.setText("Producto quitado.")

    def _render_destinations(self) -> None:
        self.destination_table.setRowCount(len(self.destinations))
        for row_index, destination in enumerate(self.destinations):
            values = (
                destination["client_label"],
                destination["address_label"],
                str(len(destination["products"])),
            )
            for column, value in enumerate(values):
                self.destination_table.setItem(row_index, column, QTableWidgetItem(value))
        if self.destinations and self.destination_table.currentRow() < 0:
            self.destination_table.setCurrentCell(0, 0)
        self._render_products(self.destination_table.currentRow())

    def _render_products(self, destination_index: int) -> None:
        products = []
        if 0 <= destination_index < len(self.destinations):
            products = self.destinations[destination_index]["products"]
        self.product_table.setRowCount(len(products))
        for row_index, product in enumerate(products):
            values = (product["product_label"], f"{product['quantity']:g}", product["unit"])
            for column, value in enumerate(values):
                self.product_table.setItem(row_index, column, QTableWidgetItem(value))

    def _save(self) -> None:
        if self.driver_combo.currentData() is None:
            self.feedback.setText("Seleccione chofer.")
            return
        if self.carrier_combo.currentData() is None:
            self.feedback.setText("El chofer seleccionado no tiene transportista asignado.")
            return
        if self.truck_combo.currentData() is None:
            self.feedback.setText("Seleccione camion / patente.")
            return
        try:
            destinations = []
            for destination in self.destinations:
                destinations.append(
                    {
                        "client": Client.get_by_id(destination["client_id"]),
                        "delivery_address": ClientAddress.get_by_id(destination["address_id"]),
                        "products": [
                            {
                                "product": Product.get_by_id(product["product_id"]),
                                "quantity": product["quantity"],
                            }
                            for product in destination["products"]
                        ],
                    }
                )
            if self.order is None:
                self.created_order = self.service.create_order(
                    carrier=Carrier.get_by_id(self.carrier_combo.currentData()),
                    driver=Driver.get_by_id(self.driver_combo.currentData()),
                    truck=Truck.get_by_id(self.truck_combo.currentData()),
                    destinations=destinations,
                    pallets=[],
                    observations=self.observations_input.text().strip() or None,
                    order_date=self.order_date.date().toPyDate(),
                )
            else:
                self.created_order = self.service.update_order(
                    self.order,
                    carrier=Carrier.get_by_id(self.carrier_combo.currentData()),
                    driver=Driver.get_by_id(self.driver_combo.currentData()),
                    truck=Truck.get_by_id(self.truck_combo.currentData()),
                    destinations=destinations,
                    pallets=[],
                    observations=self.observations_input.text().strip() or None,
                    date=self.order_date.date().toPyDate(),
                )
            self.accept()
        except Exception as exc:
            self.feedback.setText(str(exc))


class LoadOrderProductDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.product: dict | None = None
        self.setObjectName("loadOrderProductDialog")
        self.setWindowTitle("Agregar producto")
        self.resize(460, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)
        title = QLabel("Agregar producto")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        form = QGridLayout()
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("productDialogProductInput")
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setObjectName("productDialogQuantityInput")
        self.quantity_input.setRange(0, 999999)
        self.quantity_input.setDecimals(2)
        form.addWidget(QLabel("Producto"), 0, 0)
        form.addWidget(self.product_combo, 0, 1)
        form.addWidget(QLabel("Cantidad"), 1, 0)
        form.addWidget(self.quantity_input, 1, 1)
        layout.addLayout(form)
        self.feedback = QLabel("")
        self.feedback.setObjectName("productDialogFeedback")
        layout.addWidget(self.feedback)
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel_button = _action_button("cancelProductButton", "Cancelar", secondary=True)
        add_button = _action_button("confirmProductButton", "Agregar")
        footer.addWidget(cancel_button)
        footer.addWidget(add_button)
        layout.addLayout(footer)
        _fill_combo(self.product_combo, _product_options())
        cancel_button.clicked.connect(self.reject)
        add_button.clicked.connect(self._accept_product)

    def _accept_product(self) -> None:
        product_id = self.product_combo.currentData()
        quantity = self.quantity_input.value()
        if product_id is None:
            self.feedback.setText("Seleccione un producto.")
            return
        if quantity <= 0:
            self.feedback.setText("La cantidad debe ser mayor a cero.")
            return
        product = Product.get_by_id(product_id)
        self.product = {
            "product_id": product_id,
            "product_label": product.name,
            "quantity": quantity,
            "unit": product.unit,
        }
        self.accept()


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


def _can_annul_load_orders(user) -> bool:
    if user is None:
        return False
    try:
        return PermissionService().has_permission(user, "Operaciones", "anular", "Órdenes de carga")
    except (InterfaceError, OperationalError):
        return False


def _has_printed_load_order(order: LoadOrder) -> bool:
    try:
        return (
            AuditLog.select()
            .where(
                AuditLog.module == "Ordenes de carga",
                AuditLog.action == "imprimir",
                AuditLog.record_ref == f"LoadOrder:{order.id}",
            )
            .exists()
        )
    except (InterfaceError, OperationalError):
        return False


def _open_print_output(path: Path) -> None:
    target = Path(path).resolve()
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        startfile(str(target))
        return
    webbrowser.open(target.as_uri())


def _matches_load_order_query(order: LoadOrder, query: str) -> bool:
    text = " ".join(
        (
            _format_order_number(order.order_number),
            str(order.order_number),
            order.date.strftime("%d/%m/%Y"),
            order.status,
            order.carrier.name,
            order.driver.name,
            order.truck.domain,
            _summarize_order_clients(order),
            _summarize_order_deliveries(order),
            _summarize_order_products(order),
            _order_destinations_text(order),
            _order_products_text(order),
            order.observations or "",
        )
    )
    return query.lower() in text.lower()


def _can_use_menu_action(user, section: str, action: str, title: str) -> bool:
    if user is None:
        return False
    try:
        return PermissionService().has_permission(user, section, action, title)
    except (InterfaceError, OperationalError):
        return False


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


def _client_options() -> list[tuple[int, str]]:
    try:
        return [(client.id, client.name) for client in Client.select().where(Client.active == True).order_by(Client.name)]  # noqa: E712
    except (InterfaceError, OperationalError):
        return []


def _address_options(client_id: int | None = None) -> list[tuple[int, str]]:
    try:
        query = ClientAddress.select().join(Client).where(ClientAddress.active == True)  # noqa: E712
        if client_id is not None:
            query = query.where(ClientAddress.client == client_id)
        return [
            (address.id, f"{address.client.name} - {address.address}, {address.city}")
            for address in query.order_by(Client.name, ClientAddress.city)
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


def _truck_options(carrier_id: int | None = None) -> list[tuple[int, str]]:
    try:
        if carrier_id is None:
            return []
        return [
            (truck.id, truck.domain)
            for truck in Truck.select()
            .where((Truck.active == True) & (Truck.carrier == carrier_id))  # noqa: E712
            .order_by(Truck.domain)
        ]
    except (InterfaceError, OperationalError):
        return []


def _driver_options(carrier_id: int | None = None) -> list[tuple[int, str]]:
    try:
        query = Driver.select().where(Driver.active == True)  # noqa: E712
        if carrier_id is not None:
            query = query.where(Driver.carrier == carrier_id)
        return [(driver.id, driver.name) for driver in query.order_by(Driver.name)]
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
#card, #kpiCard, #contentPanel, #detailPanel, #formSection {
    background: #ffffff; border: 1px solid #d9e1ec; border-radius: 8px;
}
#card { min-height: 88px; }
#cardValue, #kpiValue { font-size: 28px; font-weight: 700; color: #111827; }
#kpiCard { min-height: 96px; }
#kpiHelper { color: #64748b; font-size: 12px; }
#detailPanel { margin-left: 8px; }
#formSection { margin-top: 2px; }
#formHint { color: #526174; font-size: 12px; }
#dialogTitle { font-size: 20px; font-weight: 700; color: #111827; }
#sectionTitle { font-size: 14px; font-weight: 700; color: #111827; }
#loadOrderDialogFeedback, #productDialogFeedback { color: #b45309; font-size: 12px; }
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
#addLoadOrderClientButton { min-width: 178px; }
#removeLoadOrderClientButton { min-width: 150px; }
#addLoadOrderProductButton, #removeLoadOrderProductButton { min-width: 132px; }
#saveLoadOrderButton { min-width: 132px; }
QTableWidget { background: #ffffff; alternate-background-color: #fbfdff; gridline-color: #edf2f7; border: 0; selection-background-color: #e8f1ff; selection-color: #0f172a; }
QHeaderView::section { background: #ffffff; color: #334155; border: 0; border-bottom: 1px solid #d9e1ec; padding: 10px; font-weight: 700; }
"""

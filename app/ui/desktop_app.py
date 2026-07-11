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
    QFileDialog,
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
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from app.config.database import initialize_demo_database, initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, TipoIVA, Truck
from app.services.auth_service import AuthService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.services.client_payment_service import ClientPaymentService
from app.services import account_statement_print_service
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.customer_payment_dialog import ClientPaymentDialog
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_workspace_spec
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow as ShellBuilder
from app.ui.master_abm import build_client_abm_page, build_master_abm_page, master_abm_configs


LOAD_ORDER_PRINTS_DIR = Path("outputs") / "load_orders"


def run_desktop_app(*, demo_mode: bool = False) -> int:
    database = _prepare_database(demo_mode=demo_mode)
    if database is not None:
        PermissionService().seed_defaults()
        _ensure_demo_user(demo_mode=demo_mode)
        if demo_mode:
            _seed_demo_masters()
    app = QApplication.instance() or QApplication([])
    login = LoginWindow(demo_mode=demo_mode)
    if login.show() != QDialog.Accepted:
        return 0
    user = login.authenticated_user
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
        ensure_runtime_schema(database)
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
        self._add_page("customer_ledger", self._customer_ledger_page())
        self._add_page("legacy_dbf_import", self._legacy_dbf_import_page())
        self._add_page("placeholder", self._placeholder_page())
        self.nav.currentRowChanged.connect(self._navigate)
        self.nav.setCurrentRow(0)

    def _add_master_pages(self) -> None:
        for route, config in master_abm_configs().items():
            if route == "clients":
                self._add_page(
                    route,
                    build_client_abm_page(
                        user=self.user,
                        current_user=self.shell.username,
                        parent=self,
                    ),
                )
            else:
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
            self._refresh_route(route)

    def _navigate_to_route(self, route: str) -> None:
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            if item and item.data(Qt.UserRole) == route:
                self.nav.setCurrentRow(i)
                return

    def _refresh_route(self, route: str) -> None:
        page_index = self._route_indexes.get(route)
        if page_index is None:
            return
        page = self.stack.widget(page_index)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _refresh_master_routes(self) -> None:
        for route in ("clients", "addresses", "products", "carriers", "drivers", "trucks"):
            self._refresh_route(route)

    def _handle_dashboard_new_load_order(self) -> None:
        self._navigate_to_route("load_orders")
        page = self.stack.currentWidget()
        if page is None:
            return
        btn = page.findChild(QPushButton, "newLoadOrderButton")
        if btn and btn.isEnabled():
            btn.click()

    def _handle_dashboard_search_load_order(self) -> None:
        self._navigate_to_route("load_orders")
        page = self.stack.currentWidget()
        if page is None:
            return
        search_input = page.findChild(QLineEdit, "loadOrderSearchInput")
        if search_input:
            search_input.setFocus()
            search_input.selectAll()

    def _handle_dashboard_new_client(self) -> None:
        self._navigate_to_route("clients")
        page = self.stack.currentWidget()
        if page is None:
            return
        btn = page.findChild(QPushButton, "newClientButton")
        if btn and btn.isEnabled():
            btn.click()

    def _handle_dashboard_open_customer_ledger(self) -> None:
        self._navigate_to_route("customer_ledger")

    def _handle_dashboard_register_payment(self) -> None:
        self._open_payment_dialog(preset_client=None)

    def _customer_ledger_page(self) -> QWidget:
        return CustomerLedgerPage(
            current_user=self.shell.username,
            register_payment_callback=self._open_payment_dialog,
            print_statement_callback=self._print_account_statement,
            parent=self,
        )

    def _print_account_statement(self, client) -> None:
        if not hasattr(self, "_print_output_dir"):
            self._print_output_dir = Path.cwd()
        try:
            pdf_path = account_statement_print_service.export_account_statement(client, self._print_output_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Extracto", f"No se pudo generar el extracto: {exc}")
            return
        _open_print_output(pdf_path)

    def _open_payment_dialog(self, preset_client=None) -> None:
        try:
            dialog = ClientPaymentDialog(
                current_user=self.shell.username,
                preset_client=preset_client,
                parent=self,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Pago", f"No se pudo abrir el formulario: {exc}")
            return
        if dialog.exec_() == QDialog.Accepted:
            payment = dialog.registered_payment()
            if payment is not None:
                self._refresh_customer_ledger_after_payment()

    def _refresh_customer_ledger_after_payment(self) -> None:
        page = self.stack.widget(self._route_indexes.get("customer_ledger", -1))
        if isinstance(page, CustomerLedgerPage):
            page.refresh()

    def _dashboard_page(self) -> QWidget:
        spec = DashboardService().view_spec(demo_mode=True)
        page = _page(spec.title, "Vista general de actividad y accesos frecuentes")
        layout = page.layout()
        actions = QHBoxLayout()
        for action in spec.quick_actions:
            button = QPushButton(action.title)
            button.setObjectName(f"dashboard{action.title.replace(' ', '')}")
            button.setEnabled(action.enabled)
            button.setMinimumHeight(52)
            if action.enabled and action.route_key:
                if action.route_key == "load_orders.new":
                    button.clicked.connect(self._handle_dashboard_new_load_order)
                elif action.route_key == "load_orders.search":
                    button.clicked.connect(self._handle_dashboard_search_load_order)
                elif action.route_key == "clients.new":
                    button.clicked.connect(self._handle_dashboard_new_client)
                elif action.route_key == "customer_ledger.view":
                    button.clicked.connect(self._handle_dashboard_open_customer_ledger)
                elif action.route_key == "customer_ledger.register_payment":
                    button.clicked.connect(self._handle_dashboard_register_payment)
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
        refreshing_selection: dict[str, bool] = {"value": False}

        layout.addWidget(_load_order_metrics_strip(service))

        feedback = QLabel("")
        feedback.setObjectName("loadOrderFeedback")

        left_panel = QFrame()
        left_panel.setObjectName("contentPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        actions = QHBoxLayout()
        actions.setContentsMargins(10, 10, 10, 6)
        actions.setSpacing(8)
        new_button = _action_button("newLoadOrderButton", "Nuevo")
        edit_button = _action_button("editLoadOrderButton", "Editar", secondary=True)
        issue_button = _action_button("issueLoadOrderButton", "Emitir")
        close_button = _action_button("closeLoadOrderButton", "Cerrar")
        annul_button = _action_button("annulLoadOrderButton", "Anular")
        print_button = _action_button("printLoadOrderButton", "Imprimir")
        budget_button = _action_button("budgetLoadOrderButton", "Presupuesto", secondary=True)
        _set_button_icon(new_button, QStyle.SP_FileIcon)
        _set_button_icon(edit_button, QStyle.SP_FileDialogDetailedView)
        _set_button_icon(issue_button, QStyle.SP_DialogApplyButton)
        _set_button_icon(close_button, QStyle.SP_DialogCloseButton)
        _set_button_icon(print_button, QStyle.SP_FileDialogContentsView)
        _set_button_icon(budget_button, QStyle.SP_FileDialogInfoView)
        _set_button_icon(annul_button, QStyle.SP_TrashIcon)
        search_input = QLineEdit()
        search_input.setObjectName("loadOrderSearchInput")
        search_input.setPlaceholderText("Buscar orden, cliente, destino, producto, chofer...")
        search_input.setMinimumWidth(220)
        search_button = _action_button("searchLoadOrderButton", "Buscar", secondary=True)
        _set_button_icon(search_button, QStyle.SP_FileDialogContentsView)
        for button in (new_button, edit_button, issue_button, close_button, print_button, budget_button, annul_button):
            actions.addWidget(button)
        actions.addStretch(1)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(10, 0, 10, 10)
        search_row.setSpacing(8)
        search_row.addWidget(search_input, 1)
        search_row.addWidget(search_button)

        left_layout.addLayout(actions)
        left_layout.addLayout(search_row)

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
        layout.addWidget(left_panel, 1)

        def refresh(*, query: str | None = None) -> None:
            rows = service.list_orders() if hasattr(service, "list_orders") else []
            if not hasattr(service, "list_orders"):
                feedback.setText("Listado operativo pendiente de la capa funcional correspondiente.")
            query = (query if query is not None else search_input.text()).strip()
            if query:
                rows = [order for order in rows if _matches_load_order_query(order, query)]
            selected_id = selected_order_id["value"] if selected_order_id["value"] is not None else None
            if rows and not any(order.id == selected_id for order in rows):
                selected_id = rows[0].id
                selected_order_id["value"] = selected_id
            selected_ids = {selected_id} if selected_id is not None else set()
            refreshing_selection["value"] = True
            try:
                table.setRowCount(len(rows) + len(selected_ids))
                visual_row = 0
                selected_row = 0
                for order in rows:
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
                        table.setItem(visual_row, column, QTableWidgetItem(value))
                    table.item(visual_row, 0).setData(Qt.UserRole, order.id)
                    table.item(visual_row, 9).setForeground(_status_color(order.status))
                    if order.id == selected_id:
                        selected_row = visual_row
                        visual_row += 1
                        _add_load_order_detail_row(table, visual_row, order, open_detail_dialog)
                    visual_row += 1
                if rows:
                    table.setCurrentCell(selected_row, 0)
                else:
                    selected_order_id["value"] = None
                    clear_detail()
            finally:
                refreshing_selection["value"] = False
            if rows:
                load_selected(selected_row, rebuild_detail=False)

        def selected_order() -> LoadOrder | None:
            if selected_order_id["value"] is None:
                return None
            return LoadOrder.get_by_id(selected_order_id["value"])

        def load_selected(row: int, *, rebuild_detail: bool = True) -> None:
            if refreshing_selection["value"]:
                return
            if row < 0:
                return
            item = table.item(row, 0)
            if item is None:
                return
            order = LoadOrder.get_by_id(item.data(Qt.UserRole))
            previous_id = selected_order_id["value"]
            selected_order_id["value"] = order.id
            if rebuild_detail and previous_id != order.id:
                refresh()
                return
            set_action_state(order)

        def clear_detail() -> None:
            issue_button.setEnabled(False)
            issue_button.setToolTip("Seleccione una orden pendiente para emitir.")
            edit_button.setEnabled(False)
            edit_button.setToolTip("Seleccione una orden pendiente para editar.")
            close_button.setEnabled(False)
            close_button.setToolTip("Seleccione una orden emitida para cerrar.")

        def set_action_state(order: LoadOrder) -> None:
            is_pending = order.is_unissued
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

        def open_detail_dialog() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para ver el detalle.")
                return
            LoadOrderDetailDialog(order, self).exec_()

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
            if not order.is_unissued:
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

        def print_order() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para imprimir.")
                return
            try:
                path = operation_service.print_order(order)
                resolved_path = Path(path).resolve()
                feedback.setText(f"PDF generado correctamente: {resolved_path}")
                try:
                    _open_print_output(resolved_path)
                except Exception as open_exc:
                    feedback.setText(
                        f"PDF generado correctamente: {resolved_path}. "
                        f"No se pudo abrir automaticamente: {open_exc}"
                    )
            except Exception as exc:
                feedback.setText(str(exc))

        def print_budget() -> None:
            order = selected_order()
            if order is None:
                feedback.setText("Seleccione una orden para presupuestar.")
                return
            try:
                path = operation_service.export_combined_budget(order)
                resolved = Path(path).resolve()
                feedback.setText(f"Presupuesto generado: {resolved}")
                try:
                    _open_print_output(resolved)
                except Exception:
                    pass
            except Exception as exc:
                feedback.setText(str(exc))

        def search_orders() -> None:
            query = search_input.text().strip()
            refresh(query=query)
            count = _load_order_table_order_count(table)
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
        print_button.clicked.connect(print_order)
        budget_button.clicked.connect(print_budget)
        refresh()
        return page

    def _placeholder_page(self) -> QWidget:
        page = _page("Módulo futuro")
        page.layout().addWidget(QLabel(future_module_message()))
        page.layout().addStretch(1)
        return page

    def _legacy_dbf_import_page(self) -> QWidget:
        page = _page("Importación DBF", "Carga de maestros desde el sistema anterior")
        layout = page.layout()
        title = QLabel("Maestros habilitados: clientes, transportistas, choferes, camiones y productos")
        title.setObjectName("legacyDbfImportTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        form = QFrame()
        form.setObjectName("formSection")
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(8)

        path_inputs: dict[str, QLineEdit] = {}
        for row, (entity, label, object_name) in enumerate(_legacy_dbf_entities()):
            form_layout.addWidget(QLabel(label), row, 0)
            path_input = QLineEdit()
            path_input.setObjectName(object_name)
            path_input.setPlaceholderText(r"C:\legacy\archivo.dbf")
            browse = _action_button(f"{object_name}BrowseButton", "Examinar", secondary=True)
            browse.clicked.connect(lambda _checked=False, target=path_input: _select_dbf_file(target, self))
            form_layout.addWidget(path_input, row, 1)
            form_layout.addWidget(browse, row, 2)
            path_inputs[entity] = path_input

        encoding_row = len(path_inputs)
        form_layout.addWidget(QLabel("Encoding"), encoding_row, 0)
        encoding_input = QLineEdit("cp1252")
        encoding_input.setObjectName("dbfEncodingInput")
        form_layout.addWidget(encoding_input, encoding_row, 1)

        source_row = encoding_row + 1
        form_layout.addWidget(QLabel("Sistema origen"), source_row, 0)
        source_input = QLineEdit("legacy_dbf")
        source_input.setObjectName("dbfSourceSystemInput")
        form_layout.addWidget(source_input, source_row, 1)
        layout.addWidget(form)

        actions = QHBoxLayout()
        run_button = _action_button("runLegacyDbfImportButton", "Importar DBF")
        actions.addWidget(run_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        feedback = QLabel("Seleccione uno o más DBF para ejecutar la importación.")
        feedback.setObjectName("legacyDbfImportFeedback")
        feedback.setWordWrap(True)
        layout.addWidget(feedback)

        table = QTableWidget(0, 5)
        table.setObjectName("legacyDbfImportSummaryTable")
        table.setHorizontalHeaderLabels(["Entidad", "Creados", "Actualizados", "Omitidos", "Errores"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(table, 1)

        def run_import() -> None:
            paths = {entity: field.text().strip() for entity, field in path_inputs.items() if field.text().strip()}
            if not paths:
                feedback.setText("Indicar al menos un archivo DBF para importar.")
                table.setRowCount(0)
                return
            try:
                summary = LegacyDbfMasterImporter().import_dbf_files(
                    paths,
                    source_system=source_input.text().strip() or "legacy_dbf",
                    encoding=encoding_input.text().strip() or "cp1252",
                )
            except Exception as exc:
                feedback.setText(f"No se pudo importar: {exc}")
                return
            _fill_legacy_import_summary(table, summary)
            self._refresh_master_routes()
            feedback.setText("Importación finalizada. Revise el resumen y los errores por entidad.")

        run_button.clicked.connect(run_import)
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


def _load_order_metrics_strip(service: LoadOrderService) -> QLabel:
    metrics = QLabel("   ".join(f"{label}: {value}" for label, value, _helper in _load_order_kpis(service)))
    metrics.setObjectName("loadOrderMetricsStrip")
    return metrics


def _set_button_icon(button: QPushButton, standard_icon: QStyle.StandardPixmap) -> None:
    button.setIcon(QApplication.style().standardIcon(standard_icon))


def _action_button(object_name: str, text: str, *, secondary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    if secondary:
        button.setProperty("secondary", True)
    return button


def _add_load_order_detail_row(table: QTableWidget, row: int, order: LoadOrder, open_detail_dialog) -> None:
    item = QTableWidgetItem("")
    item.setData(Qt.UserRole, order.id)
    table.setItem(row, 0, item)
    table.setSpan(row, 0, 1, table.columnCount())
    detail = _inline_load_order_detail_panel()
    labels: dict[str, QLabel] = detail.property("detailLabels")
    view_button: QPushButton = detail.property("viewDetailButton")
    _set_inline_load_order_detail(labels, order)
    view_button.setEnabled(True)
    view_button.clicked.connect(open_detail_dialog)
    table.setCellWidget(row, 0, detail)
    table.setRowHeight(row, 86)


def _load_order_table_order_count(table: QTableWidget) -> int:
    count = 0
    for row in range(table.rowCount()):
        item = table.item(row, 0)
        if item is not None and item.data(Qt.UserRole) is not None and table.cellWidget(row, 0) is None:
            count += 1
    return count


def _inline_load_order_detail_panel() -> QFrame:
    panel = QFrame()
    panel.setObjectName("loadOrderInlineDetailPanel")
    panel.setMinimumHeight(58)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(6)
    header = QHBoxLayout()
    title = QLabel("Detalle seleccionado")
    title.setObjectName("inlineDetailTitle")
    number = QLabel("OC-000000")
    number.setObjectName("inlineDetailOrderNumber")
    status = QLabel("-")
    status.setObjectName("inlineDetailOrderStatus")
    view_button = _action_button("viewLoadOrderDetailButton", "Ver detalle", secondary=True)
    _set_button_icon(view_button, QStyle.SP_FileDialogDetailedView)
    view_button.setEnabled(False)
    header.addWidget(title)
    header.addWidget(number)
    header.addWidget(status)
    header.addStretch(1)
    header.addWidget(view_button)
    layout.addLayout(header)
    summary = QLabel("Seleccione una orden para ver el resumen operativo.")
    summary.setObjectName("inlineDetailSummary")
    summary.setWordWrap(True)
    transport = QLabel("-")
    transport.setObjectName("inlineDetailTransport")
    transport.setWordWrap(True)
    observations = QLabel("")
    observations.setObjectName("inlineDetailObservations")
    observations.setWordWrap(True)
    layout.addWidget(summary)
    layout.addWidget(transport)
    layout.addWidget(observations)
    labels = {
        "number": number,
        "status": status,
        "summary": summary,
        "transport": transport,
        "observations": observations,
    }
    panel.setProperty("detailLabels", labels)
    panel.setProperty("viewDetailButton", view_button)
    return panel


def _legacy_dbf_entities() -> list[tuple[str, str, str]]:
    return [
        ("clients", "Clientes", "dbfClientsPathInput"),
        ("carriers", "Transportistas", "dbfCarriersPathInput"),
        ("drivers", "Choferes", "dbfDriversPathInput"),
        ("trucks", "Camiones", "dbfTrucksPathInput"),
        ("products", "Productos", "dbfProductsPathInput"),
    ]


def _select_dbf_file(target: QLineEdit, parent=None) -> None:
    file_path, _ = QFileDialog.getOpenFileName(parent, "Seleccionar DBF", "", "DBF (*.dbf);;Todos (*.*)")
    if file_path:
        target.setText(file_path)


def _fill_legacy_import_summary(table: QTableWidget, summary: dict) -> None:
    labels = {
        "clients": "Clientes",
        "carriers": "Transportistas",
        "drivers": "Choferes",
        "trucks": "Camiones",
        "products": "Productos",
    }
    table.setRowCount(len(labels))
    for row, (entity, label) in enumerate(labels.items()):
        values = summary.get(entity, {})
        errors = values.get("errors", [])
        cells = [
            label,
            str(values.get("created", 0)),
            str(values.get("updated", 0)),
            str(values.get("skipped", 0)),
            str(len(errors)),
        ]
        for column, value in enumerate(cells):
            table.setItem(row, column, QTableWidgetItem(value))
        if errors:
            table.item(row, 4).setToolTip("; ".join(str(error.get("message", error)) for error in errors))


def _detail_panel(spec) -> QFrame:
    panel = QFrame()
    panel.setObjectName("detailPanel")
    panel.setMinimumWidth(220)
    panel.setMaximumWidth(480)
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


def _set_inline_load_order_detail(labels: dict[str, QLabel], order: LoadOrder) -> None:
    first_pallet = order.pallets.first()
    labels["number"].setText(_format_order_number(order.order_number))
    labels["status"].setText(_display_status(order.status))
    labels["status"].setProperty("statusKey", _status_key(order.status))
    labels["summary"].setText(
        f"{_summarize_order_clients(order)} | {_summarize_order_deliveries(order)} | "
        f"{_summarize_order_products(order)}"
    )
    labels["transport"].setText(
        f"{order.date.strftime('%d/%m/%Y')} | {order.driver.name} | "
        f"{order.carrier.name} | {order.truck.domain} | "
        f"Pallets: {first_pallet.quantity if first_pallet else 0} | Peso: {_estimated_weight(first_pallet)}"
    )
    labels["observations"].setText(f"Obs: {order.observations}" if order.observations else "")


def _clear_inline_load_order_detail(labels: dict[str, QLabel]) -> None:
    labels["number"].setText("OC-000000")
    labels["status"].setText("-")
    labels["summary"].setText("Seleccione una orden para ver el resumen operativo.")
    labels["transport"].setText("-")
    labels["observations"].setText("")


class LoadOrderDetailDialog(QDialog):
    def __init__(self, order: LoadOrder, parent=None):
        super().__init__(parent)
        self.order = LoadOrder.get_by_id(order.id)
        self.setObjectName("loadOrderDetailDialog")
        self.setWindowTitle(f"Detalle {_format_order_number(self.order.order_number)}")
        self.setMinimumSize(820, 460)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Detalle de la orden")
        title.setObjectName("dialogTitle")
        number = QLabel(_format_order_number(self.order.order_number))
        number.setObjectName("detailOrderNumber")
        status = QLabel(_display_status(self.order.status))
        status.setObjectName("detailOrderStatus")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(number)
        header.addWidget(status)
        layout.addLayout(header)

        orders_title = QLabel("Pedidos / productos")
        orders_title.setObjectName("sectionTitle")
        layout.addWidget(orders_title)

        detail_table = QTableWidget(0, 5)
        detail_table.setObjectName("loadOrderDetailItemsTable")
        detail_table.setHorizontalHeaderLabels(("Cliente", "Destino", "Producto", "Cantidad", "Unidad"))
        detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        detail_table.verticalHeader().setVisible(False)
        detail_table.setShowGrid(False)
        detail_table.setAlternatingRowColors(True)
        detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        detail_table.setMinimumHeight(150)
        detail_table.setRowCount(len(_load_order_detail_item_rows(self.order)))
        for row, values in enumerate(_load_order_detail_item_rows(self.order)):
            for column, value in enumerate(values):
                detail_table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(detail_table, 1)

        transport_title = QLabel("Transporte y observaciones")
        transport_title.setObjectName("sectionTitle")
        layout.addWidget(transport_title)
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(8)
        for row, (label_text, value_text) in enumerate(_load_order_transport_rows(self.order)):
            label = QLabel(label_text)
            label.setObjectName("detailLabel")
            value = QLabel(value_text)
            value.setObjectName("detailValue")
            value.setWordWrap(True)
            fields.addWidget(label, row, 0, Qt.AlignTop)
            fields.addWidget(value, row, 1)
        fields.setColumnStretch(0, 0)
        fields.setColumnStretch(1, 1)
        layout.addLayout(fields)

        close_button = _action_button("closeLoadOrderDetailButton", "Cerrar", secondary=True)
        close_button.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close_button)
        layout.addStretch(1)
        layout.addLayout(footer)


def _load_order_detail_item_rows(order: LoadOrder) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for item in order.products:
        destination = item.destination
        client_name = destination.client.name if destination is not None else _summarize_order_clients(order)
        destination_text = (
            f"{destination.delivery_address.address}, {destination.delivery_address.city}"
            if destination is not None
            else _summarize_order_deliveries(order)
        )
        rows.append((client_name, destination_text, item.product.name, f"{item.quantity:g}", item.unit))
    if rows:
        return rows
    for destination in order.destinations:
        rows.append((destination.client.name, f"{destination.delivery_address.address}, {destination.delivery_address.city}", "-", "-", "-"))
    return rows or [("-", "-", "-", "-", "-")]


def _load_order_transport_rows(order: LoadOrder) -> list[tuple[str, str]]:
    first_pallet = order.pallets.first()
    return [
        ("Fecha de orden", order.date.strftime("%d/%m/%Y")),
        ("Cantidad (Pallets)", str(first_pallet.quantity if first_pallet else 0)),
        ("Peso estimado", _estimated_weight(first_pallet)),
        ("Chofer asignado", order.driver.name),
        ("Transportista", order.carrier.name),
        ("Camion / Acoplado", order.truck.domain),
        ("Observaciones", order.observations or "Sin observaciones."),
    ]


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
        # Issue #131: el alto minimo anterior (760) excedia la altura util en laptops
        # con barra de tareas visible (~720px) y dejaba los botones Guardar/Cancelar
        # cortados debajo del borde inferior. Bajamos el minimo a 600 para que el
        # QScrollArea central absorba el overflow y el footer quede siempre visible.
        self.setMinimumSize(980, 600)
        self.resize(1100, 660)
        self.setSizeGripEnabled(True)
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

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        self.step_list = QFrame()
        self.step_list.setObjectName("loadOrderEntryStepList")
        self.step_list.setMaximumWidth(180)
        self.step_list.setMinimumWidth(162)
        self.step_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        step_layout = QVBoxLayout(self.step_list)
        step_layout.setContentsMargins(8, 8, 8, 8)
        step_layout.setSpacing(6)
        step_title = QLabel("Pasos")
        step_title.setObjectName("loadOrderStepTitle")
        step_layout.addWidget(step_title)
        self.step_buttons: list[QPushButton] = []
        for index, label in enumerate(("Transporte", "Destinos", "Productos", "Revisar")):
            button = QPushButton(f"{index + 1}  {label}")
            button.setObjectName(f"loadOrderStepButton{index}")
            button.setProperty("stepNav", True)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, row=index: self._go_to_step(row))
            self.step_buttons.append(button)
            step_layout.addWidget(button)
        step_layout.addStretch(1)

        self.step_stack = QStackedWidget()
        self.step_stack.setObjectName("loadOrderEntryStepStack")
        body_layout.addWidget(self.step_list)
        body_layout.addWidget(self.step_stack, 1)

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
        self.step_stack.addWidget(header)

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
        self.destination_table = QTableWidget(0, 4)
        self.destination_table.setObjectName("loadOrderDestinationDraftTable")
        self.destination_table.setHorizontalHeaderLabels(("Cliente", "Destino", "Productos", "Total $"))
        self.destination_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.destination_table.verticalHeader().setVisible(False)
        self.destination_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.destination_table.setMinimumHeight(180)
        destination_layout.addWidget(self.destination_table)
        self.step_stack.addWidget(destination)

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
        self.product_table = QTableWidget(0, 6)
        self.product_table.setObjectName("loadOrderProductDraftTable")
        self.product_table.setHorizontalHeaderLabels(("Producto", "Cantidad", "Unidad", "P.Unit", "Dto%", "Total"))
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.product_table.setMinimumHeight(160)
        product_layout.addWidget(self.product_table)
        self.step_stack.addWidget(product)

        review = QFrame()
        review.setObjectName("formSection")
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(12, 12, 12, 12)
        review_layout.setSpacing(8)
        review_title = QLabel("Revisar orden")
        review_title.setObjectName("sectionTitle")
        review_layout.addWidget(review_title)
        self.review_table = QTableWidget(0, 6)
        self.review_table.setObjectName("loadOrderReviewTable")
        self.review_table.setHorizontalHeaderLabels(("Cliente", "Destino", "Producto", "Cantidad", "Unidad", "Total"))
        self.review_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.review_table.setMinimumHeight(260)
        review_layout.addWidget(self.review_table)
        self.step_stack.addWidget(review)

        root.addWidget(body, 1)

        self.feedback = QLabel("")
        self.feedback.setObjectName("loadOrderDialogFeedback")
        self.feedback.setWordWrap(True)
        root.addWidget(self.feedback)

        footer = QHBoxLayout()
        self.previous_step_button = _action_button("previousLoadOrderStepButton", "Anterior", secondary=True)
        self.next_step_button = _action_button("nextLoadOrderStepButton", "Siguiente", secondary=True)
        footer.addStretch(1)
        cancel_button = _action_button("cancelLoadOrderButton", "Cancelar", secondary=True)
        self.save_button = _action_button("saveLoadOrderButton", "Guardar orden")
        footer.addWidget(self.previous_step_button)
        footer.addWidget(self.next_step_button)
        footer.addWidget(cancel_button)
        footer.addWidget(self.save_button)
        root.addLayout(footer)

        self.previous_step_button.clicked.connect(self._previous_step)
        self.next_step_button.clicked.connect(self._next_step)
        add_destination_button.clicked.connect(self._add_destination)
        remove_destination_button.clicked.connect(self._remove_destination)
        add_product_button.clicked.connect(self._open_product_dialog)
        remove_product_button.clicked.connect(self._remove_product)
        self.save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)
        self.destination_table.currentCellChanged.connect(
            lambda row, _column, _previous_row, _previous_column: self._render_products(row)
        )
        self.driver_combo.currentIndexChanged.connect(lambda _index: self._refresh_from_driver())
        self.carrier_combo.currentIndexChanged.connect(lambda _index: self._update_save_button_state())
        self.truck_combo.currentIndexChanged.connect(lambda _index: self._update_save_button_state())
        self.client_combo.currentIndexChanged.connect(lambda _index: self._refresh_address_options())
        self._go_to_step(0)
        self._update_save_button_state()

    def _go_to_step(self, index: int) -> None:
        if index < 0:
            index = 0
        if index >= self.step_stack.count():
            index = self.step_stack.count() - 1
        self.step_stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.step_buttons):
            button.setChecked(button_index == index)
        self.previous_step_button.setEnabled(index > 0)
        self.next_step_button.setEnabled(index < self.step_stack.count() - 1)

    def _previous_step(self) -> None:
        self._go_to_step(self.step_stack.currentIndex() - 1)

    def _next_step(self) -> None:
        self._go_to_step(self.step_stack.currentIndex() + 1)

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
                        "precio_neto_unitario": product.precio_neto_unitario,
                        "descuento_porcentaje": product.descuento_porcentaje,
                        "total": product.total,
                    }
                    for product in destination.products
                ],
            }
            for destination in self.order.destinations.order_by()
        ]
        self._render_destinations()
        self._render_review()
        self._update_save_button_state()

    def _refresh_from_driver(self) -> None:
        driver_id = self.driver_combo.currentData()
        if driver_id is None:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            self._update_save_button_state()
            return
        try:
            driver = Driver.get_by_id(driver_id)
        except Driver.DoesNotExist:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            self._update_save_button_state()
            return
        try:
            carrier = driver.carrier
        except Carrier.DoesNotExist:
            carrier = None
        if carrier is None or not carrier.active:
            self.carrier_combo.setCurrentIndex(-1)
            _fill_combo(self.truck_combo, [])
            if carrier is None:
                self.feedback.setText("El chofer seleccionado no tiene transportista asociado.")
            else:
                self.feedback.setText("El transportista asociado al chofer esta inactivo.")
            self._update_save_button_state()
            return
        carrier_id = carrier.id
        if self.carrier_combo.findData(carrier_id) < 0:
            _fill_combo(self.carrier_combo, _carrier_options())
        _set_combo(self.carrier_combo, carrier_id)
        truck_options = _truck_options(carrier_id=carrier_id)
        _fill_combo(self.truck_combo, truck_options)
        if len(truck_options) == 1:
            self.truck_combo.setCurrentIndex(1)
        elif not truck_options:
            self.feedback.setText("No hay camiones activos para el transportista seleccionado.")
        self._update_save_button_state()

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
        new_row = len(self.destinations) - 1
        self._render_destinations()
        self.destination_table.setCurrentCell(new_row, 0)
        self._go_to_step(2)
        self.feedback.setText("Cliente/destino agregado. Ahora agregue productos.")
        self._update_save_button_state()

    def _remove_destination(self) -> None:
        row = self.destination_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            self.feedback.setText("Seleccione un cliente/destino.")
            return
        self.destinations.pop(row)
        self._render_destinations()
        self.feedback.setText("Cliente/destino quitado.")
        self._update_save_button_state()

    def _open_product_dialog(self) -> None:
        row = self.destination_table.currentRow()
        if row < 0 or row >= len(self.destinations):
            self.feedback.setText("Seleccione un cliente/destino antes de agregar productos.")
            return
        dest = self.destinations[row]
        client = None
        if dest.get("client_id"):
            try:
                client = Client.get_by_id(dest["client_id"])
            except Client.DoesNotExist:
                pass
        dialog = LoadOrderProductDialog(self, client=client)
        if dialog.exec_() != QDialog.Accepted or dialog.product is None:
            return
        self.destinations[row]["products"].append(dialog.product)
        self._render_products(row)
        self._render_destinations()
        self.destination_table.setCurrentCell(row, 0)
        self.feedback.setText("Producto agregado.")
        self._update_save_button_state()

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
        self._update_save_button_state()

    def _render_destinations(self) -> None:
        self.destination_table.setRowCount(len(self.destinations))
        for row_index, destination in enumerate(self.destinations):
            total = sum(p.get("total", 0.0) for p in destination["products"])
            values = (
                destination["client_label"],
                destination["address_label"],
                str(len(destination["products"])),
                f"$ {total:,.2f}",
            )
            for column, value in enumerate(values):
                self.destination_table.setItem(row_index, column, QTableWidgetItem(value))
        if self.destinations and self.destination_table.currentRow() < 0:
            self.destination_table.setCurrentCell(0, 0)
        self._render_products(self.destination_table.currentRow())
        self._render_review()
        self._update_save_button_state()

    def _render_products(self, destination_index: int) -> None:
        products = []
        if 0 <= destination_index < len(self.destinations):
            products = self.destinations[destination_index]["products"]
        self.product_table.setRowCount(len(products))
        for row_index, prod in enumerate(products):
            precio = prod.get("precio_neto_unitario", 0.0)
            dto_pct = prod.get("descuento_porcentaje", 0.0)
            total = prod.get("total", 0.0)
            values = (
                prod["product_label"],
                f"{prod['quantity']:g}",
                prod["unit"],
                f"$ {precio:,.2f}",
                f"{dto_pct:g}%",
                f"$ {total:,.2f}",
            )
            for column, value in enumerate(values):
                self.product_table.setItem(row_index, column, QTableWidgetItem(value))
        self._render_review()

    def _render_review(self) -> None:
        rows = []
        for destination in self.destinations:
            products = destination["products"] or [{}]
            for product in products:
                rows.append(
                    (
                        destination["client_label"],
                        destination["address_label"],
                        product.get("product_label", "-"),
                        f"{product.get('quantity', 0):g}" if product.get("quantity") else "-",
                        product.get("unit", "-"),
                        f"$ {product.get('total', 0.0):,.2f}" if product.get("total") else "-",
                    )
                )
        self.review_table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                self.review_table.setItem(row_index, column, QTableWidgetItem(value))
        self._update_save_button_state()

    def _is_ready_to_save(self) -> bool:
        if self.driver_combo.currentData() is None:
            return False
        if self.carrier_combo.currentData() is None:
            return False
        if self.truck_combo.currentData() is None:
            return False
        if not self.destinations:
            return False
        for destination in self.destinations:
            if destination.get("client_id") is None or destination.get("address_id") is None:
                return False
            products = destination.get("products") or []
            if not products:
                return False
            for product in products:
                if product.get("product_id") is None:
                    return False
                if product.get("quantity") is None or product.get("quantity") <= 0:
                    return False
        return True

    def _update_save_button_state(self) -> None:
        if not hasattr(self, "save_button"):
            return
        ready = self._is_ready_to_save()
        self.save_button.setEnabled(ready)
        if ready:
            self.save_button.setToolTip("Guardar orden.")
        else:
            self.save_button.setToolTip("Complete chofer, camion, destino y productos para guardar.")

    def _save(self) -> None:
        if not self._is_ready_to_save():
            self.feedback.setText("Complete chofer, camion, destino y productos antes de guardar.")
            self._update_save_button_state()
            return
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
                                "precio_neto_unitario": product.get("precio_neto_unitario"),
                                "descuento_porcentaje": product.get("descuento_porcentaje"),
                                "iva_porcentaje": product.get("iva_porcentaje"),
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
    def __init__(self, parent=None, *, client: Client | None = None):
        super().__init__(parent)
        self.product: dict | None = None
        self.client = client
        self.setObjectName("loadOrderProductDialog")
        self.setWindowTitle("Agregar producto")
        self.resize(500, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(10)
        title = QLabel("Agregar producto")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        self.product_combo = QComboBox()
        self.product_combo.setObjectName("productDialogProductInput")
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setObjectName("productDialogQuantityInput")
        self.quantity_input.setRange(0, 999999)
        self.quantity_input.setDecimals(2)
        self.precio_input = QDoubleSpinBox()
        self.precio_input.setObjectName("productDialogPrecioInput")
        self.precio_input.setRange(0, 99999999)
        self.precio_input.setDecimals(2)
        self.precio_input.setPrefix("$ ")
        self.descuento_input = QDoubleSpinBox()
        self.descuento_input.setObjectName("productDialogDescuentoInput")
        self.descuento_input.setRange(0, 100)
        self.descuento_input.setDecimals(2)
        self.descuento_input.setSuffix(" %")
        self.iva_input = QDoubleSpinBox()
        self.iva_input.setObjectName("productDialogIvaInput")
        self.iva_input.setRange(0, 100)
        self.iva_input.setDecimals(2)
        self.iva_input.setSuffix(" %")
        self.iva_input.setEnabled(False)

        form.addWidget(QLabel("Producto"), 0, 0)
        form.addWidget(self.product_combo, 0, 1, 1, 2)
        form.addWidget(QLabel("Cantidad"), 1, 0)
        form.addWidget(self.quantity_input, 1, 1, 1, 2)
        form.addWidget(QLabel("Precio neto unitario"), 2, 0)
        form.addWidget(self.precio_input, 2, 1, 1, 2)
        form.addWidget(QLabel("Descuento"), 3, 0)
        form.addWidget(self.descuento_input, 3, 1)
        form.addWidget(QLabel("IVA"), 3, 2)
        form.addWidget(self.iva_input, 3, 3)
        layout.addLayout(form)

        totals_grid = QGridLayout()
        totals_grid.setVerticalSpacing(4)
        self.neto_subtotal_label = QLabel("$ 0.00")
        self.neto_subtotal_label.setObjectName("productDialogNetoSubtotal")
        self.descuento_importe_label = QLabel("$ 0.00")
        self.descuento_importe_label.setObjectName("productDialogDescuentoImporte")
        self.neto_gravado_label = QLabel("$ 0.00")
        self.neto_gravado_label.setObjectName("productDialogNetoGravado")
        self.iva_importe_label = QLabel("$ 0.00")
        self.iva_importe_label.setObjectName("productDialogIvaImporte")
        self.total_label = QLabel("$ 0.00")
        self.total_label.setObjectName("productDialogTotal")
        self.total_label.setStyleSheet("font-weight: bold; font-size: 16px;")

        totals_grid.addWidget(QLabel("Neto subtotal:"), 0, 0)
        totals_grid.addWidget(self.neto_subtotal_label, 0, 1)
        totals_grid.addWidget(QLabel("Descuento:"), 1, 0)
        totals_grid.addWidget(self.descuento_importe_label, 1, 1)
        totals_grid.addWidget(QLabel("Neto gravado:"), 2, 0)
        totals_grid.addWidget(self.neto_gravado_label, 2, 1)
        totals_grid.addWidget(QLabel("IVA:"), 3, 0)
        totals_grid.addWidget(self.iva_importe_label, 3, 1)
        totals_grid.addWidget(QLabel("Total:"), 4, 0)
        totals_grid.addWidget(self.total_label, 4, 1)
        layout.addLayout(totals_grid)

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
        self.product_combo.currentIndexChanged.connect(self._on_product_changed)
        self.quantity_input.valueChanged.connect(self._recalculate)
        self.precio_input.valueChanged.connect(self._recalculate)
        self.descuento_input.valueChanged.connect(self._recalculate)
        cancel_button.clicked.connect(self.reject)
        add_button.clicked.connect(self._accept_product)

    def _on_product_changed(self) -> None:
        product_id = self.product_combo.currentData()
        if product_id is None:
            return
        try:
            product = Product.get_by_id(product_id)
        except Product.DoesNotExist:
            return
        self.precio_input.setValue(_product_price_for_client(product, self.client))
        if product.tipo_iva:
            self.iva_input.setValue(product.tipo_iva.porcentaje)
        elif self.iva_input.value() == 0:
            self.iva_input.setValue(21.0)
        if self.client and self.descuento_input.value() == 0:
            self.descuento_input.setValue(self.client.descuento_porcentaje or 0.0)
        self._recalculate()

    def _recalculate(self) -> None:
        quantity = self.quantity_input.value()
        precio = self.precio_input.value()
        descuento = self.descuento_input.value()
        iva_pct = self.iva_input.value()
        neto_subtotal = quantity * precio
        descuento_importe = neto_subtotal * descuento / 100.0
        neto_gravado = neto_subtotal - descuento_importe
        iva_importe = neto_gravado * iva_pct / 100.0
        total = neto_gravado + iva_importe
        self.neto_subtotal_label.setText(f"$ {neto_subtotal:,.2f}")
        self.descuento_importe_label.setText(f"$ {descuento_importe:,.2f}")
        self.neto_gravado_label.setText(f"$ {neto_gravado:,.2f}")
        self.iva_importe_label.setText(f"$ {iva_importe:,.2f}")
        self.total_label.setText(f"$ {total:,.2f}")

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
            "precio_neto_unitario": self.precio_input.value(),
            "descuento_porcentaje": self.descuento_input.value(),
            "iva_porcentaje": self.iva_input.value(),
            "neto_subtotal": quantity * self.precio_input.value(),
            "descuento_importe": quantity * self.precio_input.value() * self.descuento_input.value() / 100.0,
            "neto_gravado": quantity * self.precio_input.value() * (1 - self.descuento_input.value() / 100.0),
            "iva_importe": quantity * self.precio_input.value() * (1 - self.descuento_input.value() / 100.0) * self.iva_input.value() / 100.0,
            "total": quantity * self.precio_input.value() * (1 - self.descuento_input.value() / 100.0) * (1 + self.iva_input.value() / 100.0),
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
    return {"Borrador": "Pendiente", "Preparacion": "Pendiente", "Cerrada": "Entregada"}.get(status, status)


def _status_key(status: str) -> str:
    return _display_status(status).replace(" ", "")


def _status_color(status: str):
    colors = {
        "Borrador": Qt.darkYellow,
        "Preparacion": Qt.darkYellow,
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


def _ensure_demo_user(*, demo_mode: bool = False):
    if not demo_mode:
        return
    service = AuthService()
    if service.authenticate("demo", "demo"):
        return
    service.create_user("demo", "demo", "Administrador")


def _seed_demo_masters():
    if _demo_data_exists():
        return
    carrier = Carrier.get_or_create(
        name="Transportista Demo SRL",
        defaults={"cuit": "30777777771", "phone": "3764-111111"},
    )[0]
    driver = Driver.get_or_create(
        name="Chofer Demo",
        defaults={"carrier": carrier, "document": "DNI12345678", "phone": "3764-111112"},
    )[0]
    driver.carrier = carrier
    driver.available = True
    driver.save()
    Truck.get_or_create(domain="ABC123", defaults={"carrier": carrier})

    client_1 = Client.get_or_create(
        cuit="30777777772",
        defaults={
            "name": "Demo 1",
            "iva_condition": "RI",
            "contact": "Demo Principal",
            "descuento_porcentaje": 10.0,
            "lista_precios": 1,
        },
    )[0]
    client_1.lista_precios = 1
    client_1.save()
    _ensure_address(client_1, "Entrega Posadas", "Posadas", active=True)
    _ensure_address(client_1, "Entrega Eldorado", "Eldorado", active=True)

    client_2 = Client.get_or_create(
        cuit="30777777773",
        defaults={"name": "Demo 2", "iva_condition": "RI", "contact": "Demo Secundario", "lista_precios": 2},
    )[0]
    client_2.lista_precios = 2
    client_2.save()
    _ensure_address(client_2, "Entrega Garuhape", "Garuhape", active=True)

    client_inactive = Client.get_or_create(
        cuit="30777777774",
        defaults={"name": "Sin Entregas Activas", "iva_condition": "RI"},
    )[0]
    _ensure_address(client_inactive, "Direccion inactiva", "Posadas", active=False)

    iva_default = TipoIVA.iva_default()
    _ensure_demo_product("Fecula de mandioca", "kg", iva_default, (18000.0, 19000.0, 20000.0, 21000.0))
    _ensure_demo_product("Fecula de maiz", "kg", iva_default, (9500.0, 10000.0, 10500.0, 11000.0))


def _ensure_address(client: Client, label: str, city: str, *, active: bool):
    existing = ClientAddress.get_or_none(
        (ClientAddress.client == client)
        & (ClientAddress.address_type == "entrega")
        & (ClientAddress.province == "Misiones")
        & (ClientAddress.city == city)
        & (ClientAddress.address == label)
    )
    if existing is not None:
        if existing.active != active:
            existing.active = active
        existing.save()
        return existing
    return ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city=city,
        address=label,
        is_primary=active,
        active=active,
    )


def _ensure_demo_product(name: str, unit: str, iva_default: TipoIVA, prices: tuple[float, float, float, float]) -> Product:
    product, _ = Product.get_or_create(
        name=name,
        defaults={
            "unit": unit,
            "precio_neto_base": prices[0],
            "precio_lista_1": prices[0],
            "precio_lista_2": prices[1],
            "precio_lista_3": prices[2],
            "precio_lista_4": prices[3],
            "tipo_iva": iva_default,
        },
    )
    changed = False
    for field, value in {
        "precio_neto_base": prices[0],
        "precio_lista_1": prices[0],
        "precio_lista_2": prices[1],
        "precio_lista_3": prices[2],
        "precio_lista_4": prices[3],
        "tipo_iva": iva_default,
    }.items():
        if getattr(product, field) != value:
            setattr(product, field, value)
            changed = True
    if changed:
        product.save()
    return product


def _product_price_for_client(product: Product, client: Client | None) -> float:
    price_list = client.lista_precios if client is not None else 1
    if price_list not in (1, 2, 3, 4):
        price_list = 1
    value = getattr(product, f"precio_lista_{price_list}") or 0.0
    if value:
        return value
    return product.precio_neto_base or 0.0


def _demo_data_exists() -> bool:
    try:
        return Carrier.select().count() > 0
    except (InterfaceError, OperationalError):
        return False


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
#loadOrderMetricsStrip {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
    padding: 0 2px 4px 2px;
}
#card, #kpiCard, #contentPanel, #detailPanel, #loadOrderInlineDetailPanel, #formSection {
    background: #ffffff; border: 1px solid #d9e1ec; border-radius: 8px;
}
#card { min-height: 88px; }
#cardValue, #kpiValue { font-size: 28px; font-weight: 700; color: #111827; }
#kpiCard { min-height: 96px; }
#kpiHelper { color: #64748b; font-size: 12px; }
#loadOrderInlineDetailPanel {
    background: #fbfdff;
    border-top: 1px solid #d9e1ec;
    border-left: 0;
    border-right: 0;
    border-bottom: 0;
    border-radius: 0;
}
#formSection { margin-top: 2px; }
#formHint { color: #526174; font-size: 12px; }
#dialogTitle { font-size: 20px; font-weight: 700; color: #111827; }
#sectionTitle { font-size: 14px; font-weight: 700; color: #111827; }
#loadOrderEntryStepList {
    background: #ffffff;
    border: 1px solid #d9e1ec;
    border-radius: 8px;
}
#loadOrderStepTitle {
    color: #64748b;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px 6px 6px;
}
QPushButton[stepNav="true"] {
    background: #ffffff;
    color: #334155;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 6px;
    min-height: 34px;
    padding: 7px 8px;
    text-align: left;
    font-weight: 700;
}
QPushButton[stepNav="true"]:hover {
    background: #f8fafc;
    border: 1px solid #d9e1ec;
    border-left: 3px solid #94a3b8;
}
QPushButton[stepNav="true"]:checked {
    background: #e8f1ff;
    color: #0b6fdc;
    border: 1px solid #b7d3f6;
    border-left: 3px solid #0b6fdc;
}
#loadOrderDialogFeedback, #productDialogFeedback { color: #b45309; font-size: 12px; }
#detailTitle { font-size: 16px; font-weight: 700; color: #111827; }
#detailOrderNumber { color: #0b6fdc; font-size: 20px; font-weight: 700; margin-top: 6px; }
#detailLabel { color: #64748b; font-size: 12px; margin-top: 7px; }
#detailValue { color: #172033; font-size: 13px; }
#inlineDetailTitle { color: #334155; font-size: 13px; font-weight: 700; }
#inlineDetailOrderNumber { color: #0b6fdc; font-size: 15px; font-weight: 700; }
#inlineDetailOrderStatus { color: #64748b; font-size: 13px; font-weight: 700; }
#inlineDetailSummary { color: #172033; font-size: 12px; font-weight: 600; }
#inlineDetailTransport, #inlineDetailObservations { color: #526174; font-size: 12px; }
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
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    color: #172033;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    min-height: 34px;
    padding: 6px 10px;
    selection-background-color: #e8f1ff;
    selection-color: #0f172a;
}
QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border: 1px solid #94a3b8;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #0b6fdc;
    background: #fbfdff;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    border: 1px solid #e2e8f0;
}
QLineEdit::placeholder {
    color: #94a3b8;
}
QSpinBox, QDoubleSpinBox {
    padding-right: 30px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #d9e1ec;
    border-bottom: 1px solid #d9e1ec;
    border-top-right-radius: 6px;
    background: #f8fafc;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border-left: 1px solid #d9e1ec;
    border-bottom-right-radius: 6px;
    background: #f8fafc;
}
QComboBox, QDateEdit {
    background: #ffffff;
    color: #172033;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    min-height: 34px;
    padding: 6px 34px 6px 10px;
}
QComboBox:hover, QDateEdit:hover { border: 1px solid #94a3b8; }
QComboBox:focus, QDateEdit:focus { border: 1px solid #0b6fdc; background: #fbfdff; }
QComboBox:disabled, QDateEdit:disabled { background: #f1f5f9; color: #94a3b8; border: 1px solid #e2e8f0; }
QComboBox::drop-down, QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #d9e1ec;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background: #f8fafc;
}
QComboBox::down-arrow, QDateEdit::down-arrow {
    image: url(app/ui/assets/chevron-down.svg);
    width: 12px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #172033;
    border: 1px solid #cbd5e1;
    selection-background-color: #e8f1ff;
    selection-color: #0f172a;
    padding: 4px;
    outline: 0;
}
#addLoadOrderClientButton { min-width: 178px; }
#removeLoadOrderClientButton { min-width: 150px; }
#addLoadOrderProductButton, #removeLoadOrderProductButton { min-width: 132px; }
#saveLoadOrderButton { min-width: 132px; }
QTableWidget { background: #ffffff; alternate-background-color: #fbfdff; gridline-color: #edf2f7; border: 0; selection-background-color: #e8f1ff; selection-color: #0f172a; }
QHeaderView::section { background: #ffffff; color: #334155; border: 0; border-bottom: 1px solid #d9e1ec; padding: 10px; font-weight: 700; }
"""

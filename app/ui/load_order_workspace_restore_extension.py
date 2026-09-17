from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Client
from app.services.load_order_closure_service import LoadOrderClosureService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback
import app.ui.desktop_app as desktop


_INSTALLED = False


def install_load_order_workspace_restore_extension() -> None:
    """Restaura el workspace Glass V2 que fue revertido accidentalmente por 098da731."""
    global _INSTALLED
    if _INSTALLED:
        return
    desktop.FemagDesktopWindow._load_order_page = _restored_load_order_page
    _INSTALLED = True


def _restored_load_order_page(self):
    spec = desktop.build_load_order_workspace_spec()
    page = desktop._page(spec.title, spec.subtitle)
    page.setObjectName("loadOrdersPage")
    layout = page.layout()
    service = LoadOrderService(current_user=self.shell.username)
    closure_service = LoadOrderClosureService(current_user=self.shell.username)
    operation_service = LoadOrderOperationService(
        current_user=self.shell.username,
        prints_dir=desktop.LOAD_ORDER_PRINTS_DIR,
    )
    selected_order_id: dict[str, int | None] = {"value": None}
    refreshing_selection: dict[str, bool] = {"value": False}
    result_limit = 50

    layout.addWidget(desktop._load_order_metrics_strip(service))
    feedback = FormFeedback("loadOrderFeedback")

    left_panel = QFrame()
    left_panel.setObjectName("contentPanel")
    left_layout = QVBoxLayout(left_panel)
    left_layout.setContentsMargins(12, 12, 12, 12)
    left_layout.setSpacing(10)

    actions = QHBoxLayout()
    actions.setSpacing(8)
    new_button = desktop._action_button("newLoadOrderButton", "Nuevo")
    edit_button = desktop._action_button("editLoadOrderButton", "Editar", secondary=True)
    detail_button = desktop._action_button("detailLoadOrderButton", "Ver detalle", secondary=True)
    pallets_button = desktop._action_button("palletsLoadOrderButton", "Pallets", secondary=True)
    issue_button = desktop._action_button("issueLoadOrderButton", "Emitir")
    close_button = desktop._action_button("closeLoadOrderButton", "Cerrar", secondary=True)
    print_button = desktop._action_button("printLoadOrderButton", "Imprimir", secondary=True)
    reprint_button = desktop._action_button("reprintLoadOrderButton", "Reimprimir", secondary=True)
    budget_button = desktop._action_button("budgetLoadOrderButton", "Presupuesto", secondary=True)
    annul_button = desktop._action_button("annulLoadOrderButton", "Anular", secondary=True)
    annul_button.setProperty("uiRole", "danger")

    desktop._set_button_icon(new_button, QStyle.SP_FileIcon)
    desktop._set_button_icon(edit_button, QStyle.SP_FileDialogDetailedView)
    desktop._set_button_icon(detail_button, QStyle.SP_FileDialogInfoView)
    desktop._set_button_icon(pallets_button, QStyle.SP_DirOpenIcon)
    desktop._set_button_icon(issue_button, QStyle.SP_DialogApplyButton)
    desktop._set_button_icon(close_button, QStyle.SP_DialogCloseButton)
    desktop._set_button_icon(print_button, QStyle.SP_FileDialogContentsView)
    desktop._set_button_icon(reprint_button, QStyle.SP_BrowserReload)
    desktop._set_button_icon(budget_button, QStyle.SP_FileDialogInfoView)
    desktop._set_button_icon(annul_button, QStyle.SP_TrashIcon)

    can_reprint = desktop._can_reprint_load_orders(self.user)
    reprint_button.setVisible(can_reprint)
    for button in (
        new_button,
        edit_button,
        detail_button,
        pallets_button,
        issue_button,
        close_button,
        print_button,
        reprint_button,
        budget_button,
        annul_button,
    ):
        actions.addWidget(button)
    actions.addStretch(1)
    left_layout.addLayout(actions)

    filters = QFrame()
    filters.setObjectName("loadOrderFilters")
    filters_layout = QGridLayout(filters)
    filters_layout.setContentsMargins(10, 10, 10, 10)
    filters_layout.setHorizontalSpacing(10)
    filters_layout.setVerticalSpacing(8)

    order_filter = QLineEdit()
    order_filter.setObjectName("loadOrderNumberFilter")
    order_filter.setPlaceholderText("Ej.: OC-990034")

    client_filter = QComboBox()
    client_filter.setObjectName("loadOrderClientFilter")
    enable_combo_autocomplete(
        client_filter,
        placeholder="Buscar cliente...",
        hint="Escribí parte del nombre para filtrar clientes.",
    )
    client_filter.addItem("Todos los clientes", None)
    try:
        client_rows = Client.select().where(Client.active == True).order_by(Client.name)  # noqa: E712
    except Exception:
        client_rows = []
    for client in client_rows:
        client_filter.addItem(client.name, client.id)

    date_enabled = QCheckBox("Filtrar fecha")
    date_enabled.setObjectName("loadOrderDateFilterEnabled")
    date_filter = QDateEdit()
    date_filter.setObjectName("loadOrderDateFilter")
    date_filter.setCalendarPopup(True)
    date_filter.setDisplayFormat("dd/MM/yyyy")
    date_filter.setDate(QDate.currentDate())
    date_filter.setEnabled(False)
    date_enabled.toggled.connect(date_filter.setEnabled)

    search_button = desktop._action_button("searchLoadOrderButton", "Aplicar filtros")
    clear_filters_button = desktop._action_button(
        "clearLoadOrderFiltersButton", "Limpiar", secondary=True
    )
    desktop._set_button_icon(search_button, QStyle.SP_FileDialogContentsView)

    filters_layout.addWidget(QLabel("Orden"), 0, 0)
    filters_layout.addWidget(order_filter, 1, 0)
    filters_layout.addWidget(QLabel("Cliente"), 0, 1)
    filters_layout.addWidget(client_filter, 1, 1)
    filters_layout.addWidget(date_enabled, 0, 2)
    filters_layout.addWidget(date_filter, 1, 2)
    filters_layout.addWidget(search_button, 1, 3)
    filters_layout.addWidget(clear_filters_button, 1, 4)
    filters_layout.setColumnStretch(1, 1)
    left_layout.addWidget(filters)

    results_label = QLabel("")
    results_label.setObjectName("loadOrderResultsLabel")
    left_layout.addWidget(results_label)
    left_layout.addWidget(feedback)

    columns = tuple(spec.table_columns[:-1])
    table = QTableWidget(0, len(columns))
    table.setObjectName("loadOrdersTable")
    table.setHorizontalHeaderLabels(columns)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    for column, width in enumerate((115, 95, 160, 150, 165, 190, 105)):
        table.setColumnWidth(column, width)
    table.verticalHeader().setVisible(False)
    table.setShowGrid(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(False)
    left_layout.addWidget(table, 1)
    layout.addWidget(left_panel, 1)

    def _parsed_order_number() -> int | None:
        raw = order_filter.text().strip().upper()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        return int(digits) if digits else None

    def _selected_client() -> Client | None:
        text = client_filter.currentText().strip()
        index = client_filter.findText(text, Qt.MatchFixedString)
        if index < 0:
            return None
        client_id = client_filter.itemData(index)
        return Client.get_by_id(client_id) if client_id else None

    def refresh() -> None:
        if not hasattr(service, "list_orders"):
            feedback.show_info("Listado operativo pendiente de la capa funcional correspondiente.")
            return
        day = date_filter.date().toPyDate() if date_enabled.isChecked() else None
        rows = service.list_orders(
            client=_selected_client(),
            day=day,
            order_number=_parsed_order_number(),
            limit=result_limit,
        )
        selected_id = selected_order_id["value"]
        if rows and not any(order.id == selected_id for order in rows):
            selected_id = rows[0].id
            selected_order_id["value"] = selected_id

        refreshing_selection["value"] = True
        try:
            table.setRowCount(len(rows))
            selected_row = 0
            for row_index, order in enumerate(rows):
                values = (
                    desktop._format_order_number(order.order_number),
                    order.date.strftime("%d/%m/%Y"),
                    desktop._summarize_order_clients(order),
                    desktop._summarize_order_deliveries(order),
                    desktop._summarize_order_products(order),
                    desktop._load_order_pallet_progress(service, order),
                    desktop._display_status(order.status),
                )
                for column, value in enumerate(values):
                    table.setItem(row_index, column, QTableWidgetItem(value))
                table.item(row_index, 0).setData(Qt.UserRole, order.id)
                table.item(row_index, 6).setForeground(desktop._status_color(order.status))
                if order.id == selected_id:
                    selected_row = row_index
            if rows:
                table.setCurrentCell(selected_row, 0)
            else:
                selected_order_id["value"] = None
                clear_detail()
        finally:
            refreshing_selection["value"] = False

        if rows:
            load_selected(selected_row)
        active_filters = bool(
            order_filter.text().strip()
            or client_filter.currentData()
            or date_enabled.isChecked()
        )
        suffix = " (límite 50)" if len(rows) >= result_limit else ""
        mode = "filtradas" if active_filters else "más recientes"
        results_label.setText(f"Mostrando {len(rows)} órdenes {mode}{suffix}.")

    def selected_order() -> LoadOrder | None:
        if selected_order_id["value"] is None:
            return None
        return LoadOrder.get_by_id(selected_order_id["value"])

    def load_selected(row: int) -> None:
        if refreshing_selection["value"] or row < 0:
            return
        item = table.item(row, 0)
        if item is None or item.data(Qt.UserRole) is None:
            return
        order = LoadOrder.get_by_id(item.data(Qt.UserRole))
        selected_order_id["value"] = order.id
        set_action_state(order)

    def clear_detail() -> None:
        for button in (
            issue_button,
            edit_button,
            detail_button,
            pallets_button,
            close_button,
            reprint_button,
        ):
            button.setEnabled(False)

    def set_action_state(order: LoadOrder) -> None:
        is_pending = order.is_unissued
        is_issued = order.status == LoadOrder.STATUS_ISSUED
        issue_button.setEnabled(is_pending)
        edit_button.setEnabled(is_pending)
        detail_button.setEnabled(True)
        pallets_button.setEnabled(order.is_unissued or order.pallets.exists())
        close_button.setEnabled(is_issued)
        has_original_print = desktop._has_printed_load_order(order)
        reprint_button.setEnabled(can_reprint and has_original_print)

    def open_detail_dialog() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para ver el detalle.", focus_widget=table)
            return
        desktop.LoadOrderDetailDialog(order, self).exec_()

    def open_new_order_dialog() -> None:
        dialog = desktop.LoadOrderEntryDialog(service, self.shell.username, self)
        if dialog.exec_() == QDialog.Accepted and dialog.created_order is not None:
            selected_order_id["value"] = dialog.created_order.id
            refresh()
            feedback.show_success(
                f"Orden {desktop._format_order_number(dialog.created_order.order_number)} guardada."
            )

    def open_edit_order_dialog() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para editar.", focus_widget=table)
            return
        if not order.is_unissued:
            feedback.show_warning("Solo se pueden editar ordenes pendientes.", focus_widget=table)
            return
        dialog = desktop.LoadOrderEntryDialog(service, self.shell.username, self, order=order)
        if dialog.exec_() == QDialog.Accepted and dialog.created_order is not None:
            selected_order_id["value"] = dialog.created_order.id
            refresh()
            feedback.show_success(
                f"Orden {desktop._format_order_number(dialog.created_order.order_number)} actualizada."
            )

    def open_pallets_dialog() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para preparar sus pallets.", focus_widget=table)
            return
        if order.is_unissued:
            try:
                service.validate_merchandise_uniqueness(order)
            except ValueError as exc:
                feedback.show_error(
                    f"No se pueden armar los pallets: {exc} Edite la orden para corregirla."
                )
                return
        if not order.is_unissued and not order.pallets.exists():
            feedback.show_warning(
                "La orden seleccionada no tiene pallets para consultar.", focus_widget=table
            )
            return
        read_only = not order.is_unissued
        dialog = desktop.LoadOrderPalletDialog(service, order, self, read_only=read_only)
        if dialog.exec_() == QDialog.Accepted:
            selected_order_id["value"] = order.id
            refresh()
            feedback.show_success(
                f"Pallets de la orden {desktop._format_order_number(order.order_number)} guardados."
            )

    def issue() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para emitir.", focus_widget=table)
            return
        try:
            issued = operation_service.issue(order)
            selected_order_id["value"] = issued.id
            refresh()
            feedback.show_success(
                f"Orden {desktop._format_order_number(issued.order_number)} emitida."
            )
        except Exception as exc:
            feedback.show_error(str(exc), focus_widget=table)

    def annul() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para anular.", focus_widget=table)
            return
        try:
            annulled = operation_service.annul(
                order,
                can_annul=desktop._can_annul_load_orders(self.user),
            )
            selected_order_id["value"] = annulled.id
            refresh()
            feedback.show_success(
                f"Orden {desktop._format_order_number(annulled.order_number)} anulada."
            )
        except Exception as exc:
            feedback.show_error(str(exc), focus_widget=table)

    def close_order() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para cerrar.", focus_widget=table)
            return
        if order.status != LoadOrder.STATUS_ISSUED:
            feedback.show_warning("Solo se pueden cerrar ordenes emitidas.", focus_widget=table)
            return
        dialog = desktop.LoadOrderClosureDialog(
            order=order,
            current_user=self.shell.username,
            service=closure_service,
            parent=self,
        )
        if dialog.exec_() == QDialog.Accepted and dialog.closure() is not None:
            closure = dialog.closure()
            closed = LoadOrder.get_by_id(closure.order.id)
            selected_order_id["value"] = closed.id
            refresh()
            feedback.show_success(
                f"Orden {desktop._format_order_number(closed.order_number)} cerrada: "
                f"{closure_service.payment_status(closure).replace('_', ' ')}."
            )

    def print_order() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para imprimir.", focus_widget=table)
            return
        try:
            path = operation_service.print_order(order)
            resolved_path = Path(path).resolve()
            feedback.show_success(f"PDF generado correctamente: {resolved_path}")
            try:
                desktop._open_print_output(resolved_path)
            except Exception as open_exc:
                feedback.show_warning(
                    f"PDF generado correctamente: {resolved_path}. "
                    f"No se pudo abrir automaticamente: {open_exc}"
                )
            set_action_state(order)
        except Exception as exc:
            feedback.show_error(str(exc), focus_widget=table)

    def reprint_order() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para reimprimir.", focus_widget=table)
            return
        try:
            path = operation_service.reprint_order(order, can_reprint=can_reprint)
            resolved_path = Path(path).resolve()
            feedback.show_success(f"Reimpresión generada correctamente: {resolved_path}")
            try:
                desktop._open_print_output(resolved_path)
            except Exception as open_exc:
                feedback.show_warning(
                    f"Reimpresión generada correctamente: {resolved_path}. "
                    f"No se pudo abrir automaticamente: {open_exc}"
                )
            set_action_state(order)
        except Exception as exc:
            feedback.show_error(str(exc), focus_widget=table)

    def print_budget() -> None:
        order = selected_order()
        if order is None:
            feedback.show_warning("Seleccione una orden para presupuestar.", focus_widget=table)
            return
        try:
            path = operation_service.export_combined_budget(order)
            resolved = Path(path).resolve()
            feedback.show_success(f"Presupuesto generado: {resolved}")
            try:
                desktop._open_print_output(resolved)
            except Exception:
                pass
        except Exception as exc:
            feedback.show_error(str(exc), focus_widget=table)

    def clear_filters() -> None:
        order_filter.clear()
        client_filter.setCurrentIndex(0)
        date_enabled.setChecked(False)
        date_filter.setDate(QDate.currentDate())
        refresh()

    table.currentCellChanged.connect(
        lambda row, _column, _previous_row, _previous_column: load_selected(row)
    )
    table.cellDoubleClicked.connect(lambda _row, _column: open_detail_dialog())
    new_button.clicked.connect(open_new_order_dialog)
    edit_button.clicked.connect(open_edit_order_dialog)
    detail_button.clicked.connect(open_detail_dialog)
    pallets_button.clicked.connect(open_pallets_dialog)
    search_button.clicked.connect(refresh)
    clear_filters_button.clicked.connect(clear_filters)
    order_filter.returnPressed.connect(refresh)
    issue_button.clicked.connect(issue)
    close_button.clicked.connect(close_order)
    annul_button.clicked.connect(annul)
    print_button.clicked.connect(print_order)
    reprint_button.clicked.connect(reprint_order)
    budget_button.clicked.connect(print_budget)
    refresh()
    return page

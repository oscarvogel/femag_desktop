from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QTableWidget
from PyQt5.QtCore import Qt

from app.models.load_orders import LoadOrder
from app.services.load_order_operation_service import LoadOrderOperationService
import app.ui.desktop_app as desktop


_INSTALLED = False


def _safe_text(value) -> str:
    return str(value or "").strip().casefold()


def _order_matches_quick_search(order: LoadOrder, query: str) -> bool:
    needle = _safe_text(query)
    if not needle:
        return True

    values: list[str] = [
        desktop._format_order_number(order.order_number),
        getattr(getattr(order, "carrier", None), "name", ""),
        getattr(getattr(order, "driver", None), "name", ""),
        getattr(getattr(order, "truck", None), "domain", ""),
        getattr(order, "trailer_domain", ""),
    ]

    try:
        for destination in order.destinations:
            values.append(getattr(getattr(destination, "client", None), "name", ""))
    except Exception:
        pass

    try:
        for line in order.products:
            product = getattr(line, "product", None)
            values.append(getattr(product, "name", ""))
            values.append(getattr(product, "codigo", ""))
    except Exception:
        pass

    haystack = " | ".join(_safe_text(value) for value in values if value is not None)
    return needle in haystack


def install_load_order_quick_search_extension() -> None:
    """Agrega búsqueda libre y asegura presupuesto separado por cliente."""
    global _INSTALLED
    if _INSTALLED:
        return

    original = desktop.FemagDesktopWindow._load_order_page

    def wrapped(self):
        page = original(self)
        table = page.findChild(QTableWidget, "loadOrdersTable")
        filters = page.findChild(QFrame, "loadOrderFilters")
        if table is None or filters is None:
            return page

        layout = filters.layout()
        if not isinstance(layout, QGridLayout):
            return page

        quick = QLineEdit()
        quick.setObjectName("loadOrderQuickSearchInput")
        quick.setPlaceholderText(
            "Buscar por cliente, transportista, chofer, patente o artículo..."
        )
        quick.setClearButtonEnabled(True)

        row = layout.rowCount()
        layout.addWidget(QLabel("Búsqueda rápida"), row, 0)
        layout.addWidget(quick, row, 1, 1, 4)

        def apply_quick_search(text: str) -> None:
            for row_index in range(table.rowCount()):
                item = table.item(row_index, 0)
                if item is None:
                    table.setRowHidden(row_index, True)
                    continue
                order_id = item.data(Qt.UserRole)
                if order_id is None:
                    table.setRowHidden(row_index, True)
                    continue
                try:
                    order = LoadOrder.get_by_id(order_id)
                except Exception:
                    table.setRowHidden(row_index, True)
                    continue
                table.setRowHidden(
                    row_index,
                    not _order_matches_quick_search(order, text),
                )

        quick.textChanged.connect(apply_quick_search)

        budget_button = page.findChild(QPushButton, "budgetLoadOrderButton")
        feedback = page.findChild(desktop.FormFeedback, "loadOrderFeedback")
        if budget_button is not None and feedback is not None:
            try:
                budget_button.clicked.disconnect()
            except TypeError:
                pass

            def print_split_budgets() -> None:
                selected_row = table.currentRow()
                item = table.item(selected_row, 0) if selected_row >= 0 else None
                order_id = item.data(Qt.UserRole) if item is not None else None
                if not order_id:
                    feedback.show_warning(
                        "Seleccione una orden para presupuestar.", focus_widget=table
                    )
                    return

                try:
                    order = LoadOrder.get_by_id(order_id)
                    operation_service = LoadOrderOperationService(
                        current_user=self.shell.username,
                        prints_dir=desktop.LOAD_ORDER_PRINTS_DIR,
                    )
                    paths = operation_service.export_budgets(order)
                    if not paths:
                        feedback.show_warning(
                            "La orden no tiene presupuestos para generar.", focus_widget=table
                        )
                        return

                    resolved_paths = [Path(path).resolve() for path in paths]
                    feedback.show_success(
                        f"Se generaron {len(resolved_paths)} presupuesto(s) separados, uno por cliente."
                    )
                    for resolved in resolved_paths:
                        try:
                            desktop._open_print_output(resolved)
                        except Exception:
                            pass
                except Exception as exc:
                    feedback.show_error(str(exc), focus_widget=table)

            budget_button.clicked.connect(print_split_budgets)

        return page

    desktop.FemagDesktopWindow._load_order_page = wrapped
    _INSTALLED = True

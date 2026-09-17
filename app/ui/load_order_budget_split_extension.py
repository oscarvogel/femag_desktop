from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton, QTableWidget

from app.models.load_orders import LoadOrder
from app.services.load_order_operation_service import LoadOrderOperationService
import app.ui.desktop_app as desktop


_INSTALLED = False


def install_load_order_budget_split_extension() -> None:
    """Hace que Presupuesto genere/abra un PDF independiente por cliente."""
    global _INSTALLED
    if _INSTALLED:
        return

    original = desktop.FemagDesktopWindow._load_order_page

    def wrapped(self):
        page = original(self)
        button = page.findChild(QPushButton, "budgetLoadOrderButton")
        table = page.findChild(QTableWidget, "loadOrdersTable")
        feedback = page.findChild(desktop.FormFeedback, "loadOrderFeedback")
        if button is None or table is None or feedback is None:
            return page

        try:
            button.clicked.disconnect()
        except TypeError:
            pass

        def print_split_budgets() -> None:
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            order_id = item.data(Qt.UserRole) if item is not None else None
            if not order_id:
                feedback.show_warning("Seleccione una orden para presupuestar.", focus_widget=table)
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
                open_errors = []
                for resolved in resolved_paths:
                    try:
                        desktop._open_print_output(resolved)
                    except Exception as exc:
                        open_errors.append(f"{resolved.name}: {exc}")
                if open_errors:
                    feedback.show_warning(
                        "Los PDFs fueron generados, pero alguno no se pudo abrir automáticamente: "
                        + "; ".join(open_errors)
                    )
            except Exception as exc:
                feedback.show_error(str(exc), focus_widget=table)

        button.clicked.connect(print_split_budgets)
        return page

    desktop.FemagDesktopWindow._load_order_page = wrapped
    _INSTALLED = True

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHeaderView, QTableWidgetItem


def install_customer_ledger_due_date_extension() -> None:
    """Add the historical due date to the existing customer-ledger table."""
    from app.ui import customer_ledger

    base_page = customer_ledger.CustomerLedgerPage
    if getattr(base_page, "_due_date_extension_installed", False):
        return

    class CustomerLedgerPage(base_page):
        _due_date_extension_installed = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.movements_table.columnCount() == 6:
                self.movements_table.insertColumn(1)
                self.movements_table.setHorizontalHeaderItem(
                    1, QTableWidgetItem("Vencimiento")
                )
                self.movements_table.horizontalHeader().setSectionResizeMode(
                    1, QHeaderView.ResizeToContents
                )
            self.refresh()

        def _on_client_selected(
            self,
            current_row,
            current_col,
            previous_row,
            previous_col,
        ) -> None:
            super()._on_client_selected(
                current_row,
                current_col,
                previous_row,
                previous_col,
            )
            if self.movements_table.columnCount() < 7 or current_row < 0:
                return

            client = self._selected_client()
            if client is None:
                return
            movements = customer_ledger.movements_for_client(client)
            for row_index, movement in enumerate(movements):
                # Base implementation fills columns 0..5. Move the existing
                # cells one place to the right and reserve column 1 for due date.
                for column in range(5, 0, -1):
                    item = self.movements_table.takeItem(row_index, column)
                    if item is not None:
                        self.movements_table.setItem(row_index, column + 1, item)

                due_text = (
                    movement.due_date.strftime("%d/%m/%Y")
                    if movement.due_date is not None
                    else ""
                )
                due_cell = QTableWidgetItem(due_text)
                due_cell.setTextAlignment(Qt.AlignCenter)
                due_cell.setToolTip(due_text or "Sin vencimiento")
                self.movements_table.setItem(row_index, 1, due_cell)

    customer_ledger.CustomerLedgerPage = CustomerLedgerPage

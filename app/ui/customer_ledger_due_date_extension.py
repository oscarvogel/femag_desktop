from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHeaderView, QTableWidgetItem


DUE_DATE_COLUMN = 6


def install_customer_ledger_due_date_extension() -> None:
    """Add the historical due date without changing existing column positions."""
    from app.ui import customer_ledger

    base_page = customer_ledger.CustomerLedgerPage
    if getattr(base_page, "_due_date_extension_installed", False):
        return

    class CustomerLedgerPage(base_page):
        _due_date_extension_installed = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.movements_table.columnCount() == 6:
                self.movements_table.insertColumn(DUE_DATE_COLUMN)
                self.movements_table.setHorizontalHeaderItem(
                    DUE_DATE_COLUMN, QTableWidgetItem("Vencimiento")
                )
                self.movements_table.horizontalHeader().setSectionResizeMode(
                    DUE_DATE_COLUMN, QHeaderView.ResizeToContents
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
            if self.movements_table.columnCount() <= DUE_DATE_COLUMN or current_row < 0:
                return

            client = self._selected_client()
            if client is None:
                return
            movements = customer_ledger.movements_for_client(client)
            for row_index, movement in enumerate(movements):
                due_text = (
                    movement.due_date.strftime("%d/%m/%Y")
                    if movement.due_date is not None
                    else ""
                )
                due_cell = QTableWidgetItem(due_text)
                due_cell.setTextAlignment(Qt.AlignCenter)
                due_cell.setToolTip(due_text or "Sin vencimiento")
                self.movements_table.setItem(row_index, DUE_DATE_COLUMN, due_cell)

    customer_ledger.CustomerLedgerPage = CustomerLedgerPage

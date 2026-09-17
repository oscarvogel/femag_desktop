from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QTableWidget
from PyQt5.QtCore import Qt

from app.models.load_orders import LoadOrder
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
    """Agrega búsqueda libre al workspace restaurado de órdenes de carga."""
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
        return page

    desktop.FemagDesktopWindow._load_order_page = wrapped
    _INSTALLED = True

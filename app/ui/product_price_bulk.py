from __future__ import annotations

import unicodedata

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Product
from app.services.master_service import MasterService
from app.services.permission_service import PermissionService
from app.ui.form_feedback import FormFeedback
from app.ui.master_abm import normalize_master_text


def _money_text(value: float | None) -> str:
    value = value or 0.0
    return f"{value:g}"


def _parse_price(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    if not normalized:
        return 0.0
    return float(normalized)


class ProductPriceBulkPage(QWidget):
    """Pantalla dedicada para edicion masiva de precios por lista.

    - Tabla con columnas: Codigo | Descripcion | Lista 1 | Lista 2 | Lista 3 | Lista 4
    - Filtro por producto (codigo o descripcion) con normalizacion.
    - Edicion directa inline solo en columnas de precio.
    - Validacion numerica y no negativa.
    - Guardado batch via MasterService.bulk_update_product_prices.
    """

    def __init__(self, *, user, current_user: str, parent=None):
        super().__init__(parent)
        self.user = user
        self.current_user = current_user
        self._products: list[Product] = []
        self._filtered_ids: list[int] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(12)

        title = QLabel("Precios por lista")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Edición masiva — filtre por producto y edite directamente los precios")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Filtro por producto (codigo/descripcion)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filtrar por producto"))
        self.search_input = QLineEdit()
        self.search_input.setObjectName("productPriceBulkSearchInput")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setPlaceholderText("Buscar por código o descripción...")
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)

        self.search_feedback = FormFeedback("productPriceBulkSearchFeedback")
        layout.addWidget(self.search_feedback)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Guardar cambios")
        self.save_button.setObjectName("saveProductPriceBulkButton")
        self.reset_button = QPushButton("Descartar cambios")
        self.reset_button.setObjectName("resetProductPriceBulkButton")
        self.reset_button.setProperty("secondary", True)
        can_modify = self._can_modify()
        self.save_button.setEnabled(can_modify)
        if not can_modify:
            self.save_button.setToolTip("El perfil actual no permite modificar productos.")
        actions.addWidget(self.save_button)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 6)
        self.table.setObjectName("productPriceBulkTable")
        self.table.setHorizontalHeaderLabels(["Código", "Descripción", "Lista 1", "Lista 2", "Lista 3", "Lista 4"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        # Permitir edicion solo en columnas de precio via flags por item
        layout.addWidget(self.table, 1)

        self.feedback = FormFeedback("productPriceBulkFeedback")
        layout.addWidget(self.feedback)

        self.search_input.textChanged.connect(self._apply_filter)
        self.save_button.clicked.connect(self._save)
        self.reset_button.clicked.connect(self.refresh)
        self.table.cellChanged.connect(self._on_cell_changed)

    def _can_modify(self) -> bool:
        if self.user is None:
            return False
        try:
            return PermissionService().has_permission(self.user, "Maestros", "modificar", "Productos")
        except Exception:
            return False

    def refresh(self) -> None:
        self._products = list(Product.select().order_by(Product.name))
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_input.text().strip()
        normalized_query = normalize_master_text(query)
        filtered: list[Product] = []
        for product in self._products:
            if not normalized_query:
                filtered.append(product)
                continue
            haystack = normalize_master_text(f"{product.codigo or ''} {product.name}")
            if normalized_query in haystack:
                filtered.append(product)

        # Bloquear senales para no disparar _on_cell_changed durante rebuild
        self.table.blockSignals(True)
        self.table.setRowCount(len(filtered))
        self._filtered_ids = [p.id for p in filtered]
        for row_index, product in enumerate(filtered):
            # Codigo
            codigo_item = QTableWidgetItem(product.codigo or "")
            codigo_item.setFlags(codigo_item.flags() & ~Qt.ItemIsEditable)
            codigo_item.setData(Qt.UserRole, product.id)
            self.table.setItem(row_index, 0, codigo_item)
            # Descripcion
            desc_item = QTableWidgetItem(product.name)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_index, 1, desc_item)
            # Precios editables
            for col, field in enumerate(["precio_lista_1", "precio_lista_2", "precio_lista_3", "precio_lista_4"], start=2):
                raw = getattr(product, field, 0.0)
                # Fallback a precio_neto_base para lista 1 si es 0 y existe base (compatibilidad)
                if field == "precio_lista_1" and not raw:
                    raw = getattr(product, "precio_neto_base", 0.0) or 0.0
                price_item = QTableWidgetItem(_money_text(raw))
                price_item.setFlags(price_item.flags() | Qt.ItemIsEditable)
                price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                price_item.setData(Qt.UserRole, _money_text(raw))  # valor original para detectar dirty
                self.table.setItem(row_index, col, price_item)

        self.table.blockSignals(False)

        if query and not filtered:
            self.search_feedback.show_info(f"No se encontraron productos para «{query}».")
        else:
            self.search_feedback.clear_message()

        # Feedback general si no hay productos
        if not self._products:
            self.feedback.show_info("No hay productos cargados.")
        elif not filtered and not query:
            self.feedback.clear_message()

    def _on_cell_changed(self, row: int, column: int) -> None:
        if column < 2:
            return
        item = self.table.item(row, column)
        if item is None:
            return
        original = item.data(Qt.UserRole)
        if item.text().strip() == original:
            item.setBackground(Qt.white)
        else:
            # marcar fila dirty visualmente
            from PyQt5.QtGui import QColor

            item.setBackground(QColor("#FFF9C4"))

    def _collect_updates(self) -> tuple[list[dict], str | None]:
        updates: list[dict] = []
        for row in range(self.table.rowCount()):
            codigo_item = self.table.item(row, 0)
            if codigo_item is None:
                continue
            product_id = codigo_item.data(Qt.UserRole)
            row_updates: dict = {"product_id": product_id}
            has_change = False
            for col, field in enumerate(["precio_lista_1", "precio_lista_2", "precio_lista_3", "precio_lista_4"], start=2):
                item = self.table.item(row, col)
                if item is None:
                    continue
                text = item.text().strip()
                original = item.data(Qt.UserRole)
                if text == original:
                    continue
                # Validar numerico y no negativo
                try:
                    value = _parse_price(text)
                except ValueError:
                    return [], f"Fila {row+1} — Lista {col-1}: valor no numérico «{text}»."
                if value < 0:
                    return [], f"Fila {row+1} — Lista {col-1}: el precio no puede ser negativo."
                row_updates[field] = value
                has_change = True
            if has_change:
                updates.append(row_updates)
        return updates, None

    def _save(self) -> None:
        if not self._can_modify():
            self.feedback.show_warning("El perfil actual no permite modificar productos.")
            return
        updates, error = self._collect_updates()
        if error:
            self.feedback.show_error(error)
            return
        if not updates:
            self.feedback.show_info("No hay cambios para guardar.")
            return
        try:
            count = MasterService(self.current_user).bulk_update_product_prices(updates)
            self.feedback.show_success(f"Se actualizaron {count} producto(s) correctamente.")
            self.refresh()
        except Exception as exc:
            self.feedback.show_error(str(exc))


def build_product_price_bulk_page(*, user, current_user: str, parent=None) -> QWidget:
    return ProductPriceBulkPage(user=user, current_user=current_user, parent=parent)

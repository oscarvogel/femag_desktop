from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.budgets import Budget
from app.models.masters import Client, Product
from app.services.budget_service import BudgetService
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


class ManualBudgetDialog(QDialog):
    def __init__(self, *, client: Client, current_user: str, parent=None):
        super().__init__(parent)
        self.client = Client.get_by_id(client.id)
        self.current_user = current_user
        self._budget: Budget | None = None
        self.setObjectName("manualBudgetDialog")
        self.setWindowTitle("Nuevo presupuesto manual")
        self.resize(920, 620)
        self._items: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Nuevo presupuesto manual")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        client_label = QLabel(
            f"Cliente: <b>{self.client.name}</b> · "
            f"Lista de precios: {int(self.client.lista_precios or 1)}"
        )
        client_label.setWordWrap(True)
        layout.addWidget(client_label)

        form = QFormLayout()
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("manualBudgetProductCombo")
        products = list(
            Product.select()
            .where(Product.active == True)  # noqa: E712
            .order_by(Product.name)
        )
        for product in products:
            self.product_combo.addItem(product.name, product.id)
        enable_combo_autocomplete(self.product_combo)
        self.product_combo.currentIndexChanged.connect(self._sync_product_defaults)
        form.addRow("Producto", self.product_combo)

        numeric_row = QHBoxLayout()
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setObjectName("manualBudgetQuantityInput")
        self.quantity_input.setRange(0.001, 999999999.0)
        self.quantity_input.setDecimals(3)
        self.quantity_input.setValue(1.0)
        self.quantity_input.setSuffix(" ")
        numeric_row.addWidget(QLabel("Cantidad"))
        numeric_row.addWidget(self.quantity_input)

        self.unit_price_input = QDoubleSpinBox()
        self.unit_price_input.setObjectName("manualBudgetUnitPriceInput")
        self.unit_price_input.setRange(0.0, 999999999.99)
        self.unit_price_input.setDecimals(2)
        self.unit_price_input.setPrefix("$ ")
        numeric_row.addWidget(QLabel("Precio unitario"))
        numeric_row.addWidget(self.unit_price_input)

        self.discount_input = QDoubleSpinBox()
        self.discount_input.setObjectName("manualBudgetDiscountInput")
        self.discount_input.setRange(0.0, 100.0)
        self.discount_input.setDecimals(2)
        self.discount_input.setSuffix(" %")
        numeric_row.addWidget(QLabel("Descuento"))
        numeric_row.addWidget(self.discount_input)

        self.vat_input = QDoubleSpinBox()
        self.vat_input.setObjectName("manualBudgetVatInput")
        self.vat_input.setRange(0.0, 100.0)
        self.vat_input.setDecimals(2)
        self.vat_input.setSuffix(" %")
        numeric_row.addWidget(QLabel("IVA"))
        numeric_row.addWidget(self.vat_input)
        form.addRow("", numeric_row)
        layout.addLayout(form)

        add_row = QHBoxLayout()
        self.add_button = QPushButton("Agregar producto")
        self.add_button.setObjectName("manualBudgetAddItemButton")
        self.add_button.clicked.connect(self._add_item)
        add_row.addWidget(self.add_button)
        self.remove_button = QPushButton("Quitar seleccionado")
        self.remove_button.setObjectName("manualBudgetRemoveItemButton")
        self.remove_button.setProperty("secondary", True)
        self.remove_button.clicked.connect(self._remove_selected)
        add_row.addWidget(self.remove_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        self.items_table = QTableWidget(0, 7)
        self.items_table.setObjectName("manualBudgetItemsTable")
        self.items_table.setHorizontalHeaderLabels(
            ["Producto", "Cantidad", "Unidad", "P. unitario", "Desc.", "IVA", "Total"]
        )
        self.items_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.items_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.items_table, 1)

        self.total_label = QLabel("Total: $ 0,00")
        self.total_label.setObjectName("manualBudgetTotalLabel")
        self.total_label.setAlignment(Qt.AlignRight)
        layout.addWidget(self.total_label)

        self.observations_input = QTextEdit()
        self.observations_input.setObjectName("manualBudgetObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones del presupuesto (opcional)")
        self.observations_input.setMaximumHeight(86)
        layout.addWidget(self.observations_input)

        self.feedback = FormFeedback("manualBudgetFeedback")
        layout.addWidget(self.feedback)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("Confirmar presupuesto")
        confirm.setObjectName("manualBudgetConfirmButton")
        confirm.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)

        self._sync_product_defaults()

    def budget(self) -> Budget | None:
        return self._budget

    def budget_items(self) -> list[dict]:
        return [dict(item) for item in self._items]

    def observations(self) -> str | None:
        value = self.observations_input.toPlainText().strip()
        return value or None

    def _selected_product(self) -> Product | None:
        product_id = self.product_combo.currentData()
        if product_id is None:
            return None
        return Product.get_or_none(Product.id == product_id)

    def _sync_product_defaults(self, *_args) -> None:
        product = self._selected_product()
        if product is None:
            self.unit_price_input.setValue(0.0)
            self.vat_input.setValue(21.0)
            return
        price_list = int(self.client.lista_precios or 1)
        if price_list not in (1, 2, 3, 4):
            price_list = 1
        price = float(getattr(product, f"precio_lista_{price_list}") or 0.0)
        if not price:
            price = float(product.precio_neto_base or 0.0)
        self.unit_price_input.setValue(price)
        self.discount_input.setValue(float(self.client.descuento_porcentaje or 0.0))
        vat = float(product.tipo_iva.porcentaje) if product.tipo_iva_id else 21.0
        self.vat_input.setValue(vat)

    def _add_item(self) -> None:
        product = self._selected_product()
        if product is None:
            self._show_warning("Seleccione un producto.")
            return
        quantity = float(self.quantity_input.value())
        if quantity <= 0:
            self._show_warning("La cantidad debe ser mayor a cero.")
            return
        unit_price = float(self.unit_price_input.value())
        discount = float(self.discount_input.value())
        vat = float(self.vat_input.value())
        net_subtotal = round(quantity * unit_price, 2)
        discount_amount = round(net_subtotal * discount / 100.0, 2)
        net_taxable = round(net_subtotal - discount_amount, 2)
        vat_amount = round(net_taxable * vat / 100.0, 2)
        total = round(net_taxable + vat_amount, 2)
        self._items.append(
            {
                "product": product,
                "quantity": quantity,
                "unit": product.unit or "UN",
                "unit_price": unit_price,
                "discount_percentage": discount,
                "vat_percentage": vat,
                "total": total,
            }
        )
        self._reload_items()
        self.feedback.clear_message()
        self.quantity_input.setValue(1.0)

    def _remove_selected(self) -> None:
        row = self.items_table.currentRow()
        if row < 0 or row >= len(self._items):
            return
        self._items.pop(row)
        self._reload_items()

    def _reload_items(self) -> None:
        self.items_table.setRowCount(len(self._items))
        total = 0.0
        for row, item in enumerate(self._items):
            total += float(item["total"])
            values = (
                item["product"].name,
                self._quantity(item["quantity"]),
                item["unit"],
                f"$ {item['unit_price']:,.2f}",
                f"{item['discount_percentage']:.2f}%",
                f"{item['vat_percentage']:.2f}%",
                f"$ {item['total']:,.2f}",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (1, 3, 4, 5, 6):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.items_table.setItem(row, column, cell)
        self.total_label.setText(f"Total: $ {total:,.2f}")

    def _confirm(self) -> None:
        if not self._items:
            self._show_warning("Agregue al menos un producto al presupuesto.")
            return
        try:
            self._budget = BudgetService(self.current_user).create_manual(
                client=self.client,
                items=self.budget_items(),
                observations=self.observations(),
            )
        except Exception as exc:
            self._show_warning(f"No se pudo crear el presupuesto: {exc}")
            return
        self.accept()

    def _show_warning(self, message: str) -> None:
        self.feedback.show_warning(message)

    @staticmethod
    def _quantity(value: float) -> str:
        return f"{value:.0f}" if float(value).is_integer() else f"{value:.3f}".rstrip("0").rstrip(".")

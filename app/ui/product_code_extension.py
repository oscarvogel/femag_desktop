from __future__ import annotations

from decimal import Decimal

from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout, QLabel, QLineEdit

from app.models.masters import PRODUCT_KIND_LABELS, Product, TipoIVA, product_display_label
from app.services.master_service import MasterService
from app.ui.combo_autocomplete import enable_combo_autocomplete


def install_product_code_extension() -> None:
    """Extend the product master with a stable editable business code."""
    from app.ui import master_abm

    if getattr(master_abm.master_abm_configs, "_product_code_extension_installed", False):
        return
    base_dialog = master_abm.ProductEntryDialog

    class ProductCodeEntryDialog(base_dialog):
        def _build(self) -> None:
            layout = master_abm._entry_layout(self, "Producto / presentacion")
            form = QGridLayout()
            self.code_input = QLineEdit()
            self.code_input.setObjectName("productCodeInput")
            self.code_input.setPlaceholderText("Ej. 100, 200-A, MA-210")
            self.name_input = QLineEdit()
            self.name_input.setObjectName("productNameInput")
            self.unit_input = QLineEdit()
            self.unit_input.setObjectName("productUnitInput")
            self.weight_input = QDoubleSpinBox()
            self.weight_input.setObjectName("productWeightKgInput")
            self.weight_input.setRange(0, 999999999)
            self.weight_input.setDecimals(3)
            self.weight_input.setSuffix(" kg")
            self.kind_input = QComboBox()
            self.kind_input.setObjectName("productKindInput")
            enable_combo_autocomplete(self.kind_input, placeholder="Buscar tipo...")
            for value, label in PRODUCT_KIND_LABELS.items():
                self.kind_input.addItem(label, value)
            self.iva_input = QComboBox()
            self.iva_input.setObjectName("productIvaTypeInput")
            enable_combo_autocomplete(self.iva_input, placeholder="Buscar IVA...")
            iva_default = TipoIVA.iva_default()
            for tipo_iva in TipoIVA.select().where(TipoIVA.activo == True).order_by(TipoIVA.nombre):  # noqa: E712
                self.iva_input.addItem(f"{tipo_iva.nombre} ({tipo_iva.porcentaje:g}%)", tipo_iva.id)
            default_index = self.iva_input.findData(iva_default.id)
            if default_index >= 0:
                self.iva_input.setCurrentIndex(default_index)
            self.price_list_1_input = QLineEdit()
            self.price_list_1_input.setObjectName("productPriceList1Input")
            self.price_list_2_input = QLineEdit()
            self.price_list_2_input.setObjectName("productPriceList2Input")
            self.price_list_3_input = QLineEdit()
            self.price_list_3_input.setObjectName("productPriceList3Input")
            self.price_list_4_input = QLineEdit()
            self.price_list_4_input.setObjectName("productPriceList4Input")

            form.addWidget(QLabel("Código"), 0, 0)
            form.addWidget(self.code_input, 0, 1)
            form.addWidget(QLabel("Producto"), 1, 0)
            form.addWidget(self.name_input, 1, 1)
            form.addWidget(QLabel("Clasificación"), 2, 0)
            form.addWidget(self.kind_input, 2, 1)
            form.addWidget(QLabel("Unidad"), 3, 0)
            form.addWidget(self.unit_input, 3, 1)
            form.addWidget(QLabel("Peso unitario"), 4, 0)
            form.addWidget(self.weight_input, 4, 1)
            form.addWidget(QLabel("Tipo de IVA"), 5, 0)
            form.addWidget(self.iva_input, 5, 1)
            form.addWidget(QLabel("Lista 1"), 6, 0)
            form.addWidget(self.price_list_1_input, 6, 1)
            form.addWidget(QLabel("Lista 2"), 7, 0)
            form.addWidget(self.price_list_2_input, 7, 1)
            form.addWidget(QLabel("Lista 3"), 8, 0)
            form.addWidget(self.price_list_3_input, 8, 1)
            form.addWidget(QLabel("Lista 4"), 9, 0)
            form.addWidget(self.price_list_4_input, 9, 1)
            layout.addLayout(form)
            self.feedback = master_abm._entry_feedback(layout)
            master_abm._entry_footer(layout, self, "saveProductButton", self._save)

        def _load_record(self) -> None:
            if self.record_id is None:
                self.unit_input.setText("kg")
                return
            product = Product.get_by_id(self.record_id)
            if product.tipo_iva_id is not None and self.iva_input.findData(product.tipo_iva_id) < 0:
                tipo_iva = product.tipo_iva
                self.iva_input.addItem(
                    f"{tipo_iva.nombre} ({tipo_iva.porcentaje:g}%) — Inactivo",
                    tipo_iva.id,
                )
            self.code_input.setText(product.codigo or "")
            self.name_input.setText(product.name)
            self.unit_input.setText(product.unit)
            self.weight_input.setValue(float(product.peso_unitario_kg))
            self.kind_input.setCurrentIndex(max(self.kind_input.findData(product.product_kind or "revisar"), 0))
            if product.tipo_iva_id is not None:
                self.iva_input.setCurrentIndex(self.iva_input.findData(product.tipo_iva_id))
            self.price_list_1_input.setText(master_abm._money_text(product.precio_lista_1 or product.precio_neto_base))
            self.price_list_2_input.setText(master_abm._money_text(product.precio_lista_2))
            self.price_list_3_input.setText(master_abm._money_text(product.precio_lista_3))
            self.price_list_4_input.setText(master_abm._money_text(product.precio_lista_4))

        def _save(self) -> None:
            codigo = self.code_input.text().strip()
            name = self.name_input.text().strip()
            unit = self.unit_input.text().strip()
            if not codigo or not name or not unit:
                focus_widget = self.code_input if not codigo else self.name_input if not name else self.unit_input
                self.feedback.show_warning("Complete código, producto y unidad.", focus_widget=focus_widget)
                return
            try:
                prices = {
                    "precio_lista_1": master_abm._parse_float(self.price_list_1_input.text()),
                    "precio_lista_2": master_abm._parse_float(self.price_list_2_input.text()),
                    "precio_lista_3": master_abm._parse_float(self.price_list_3_input.text()),
                    "precio_lista_4": master_abm._parse_float(self.price_list_4_input.text()),
                }
                tipo_iva_id = self.iva_input.currentData()
                tipo_iva = TipoIVA.get_by_id(tipo_iva_id) if tipo_iva_id is not None else None
                service = MasterService(self.current_user)
                if self.record_id is None:
                    self.saved_record = service.create_product(
                        name,
                        unit,
                        codigo=codigo,
                        peso_unitario_kg=Decimal(str(self.weight_input.value())),
                        product_kind=self.kind_input.currentData(),
                        tipo_iva=tipo_iva,
                        **prices,
                    )
                else:
                    self.saved_record = service.update_product(
                        Product.get_by_id(self.record_id),
                        name,
                        unit,
                        codigo=codigo,
                        peso_unitario_kg=Decimal(str(self.weight_input.value())),
                        product_kind=self.kind_input.currentData(),
                        tipo_iva=tipo_iva,
                        **prices,
                    )
                self.accept()
            except Exception as exc:
                self.feedback.show_error(str(exc), focus_widget=self.code_input)

    def product_rows() -> list[list[object]]:
        try:
            return [
                [
                    product.id,
                    product.codigo or "",
                    product.name,
                    product.unit,
                    f"{product.peso_unitario_kg:.3f} kg" if product.peso_unitario_kg > 0 else "Peso pendiente",
                    master_abm.product_kind_label(product.product_kind),
                    "Sí" if master_abm.product_is_loadable(product) else "No",
                    "Pendiente" if product.review_required else "Confirmado",
                    master_abm._money_text(product.precio_lista_1 or product.precio_neto_base),
                    master_abm._money_text(product.precio_lista_2),
                    master_abm._money_text(product.precio_lista_3),
                    master_abm._money_text(product.precio_lista_4),
                    "Activo" if product.active else "Inactivo",
                ]
                for product in Product.select().order_by(Product.codigo, Product.name)
            ]
        except (master_abm.InterfaceError, master_abm.OperationalError):
            return []

    base_configs = master_abm.master_abm_configs

    def master_abm_configs() -> dict[str, master_abm.MasterAbmConfig]:
        configs = base_configs()
        configs["products"] = master_abm.MasterAbmConfig(
            "Productos",
            ["Código", "Producto", "Unidad", "Peso", "Clasificación", "Órdenes", "Revisión", "Lista 1", "Lista 2", "Lista 3", "Lista 4", "Estado"],
            product_rows,
            ProductCodeEntryDialog,
            "newProductButton",
            "editProductButton",
            search_placeholder="Buscar productos por código o nombre...",
        )
        return configs

    master_abm_configs._product_code_extension_installed = True
    master_abm.master_abm_configs = master_abm_configs


def install_desktop_product_code_extension() -> None:
    """Show article codes in operational product combos so autocomplete finds either value."""
    from app.ui import desktop_app

    if getattr(desktop_app, "_product_code_extension_installed", False):
        return

    def product_options() -> list[tuple[int, str]]:
        try:
            return [
                (product.id, product_display_label(product))
                for product in Product.select()
                .where((Product.active == True) & (Product.product_kind == "producto"))  # noqa: E712
                .order_by(Product.codigo, Product.name)
            ]
        except (desktop_app.InterfaceError, desktop_app.OperationalError):
            return []

    desktop_app._product_options = product_options
    desktop_app._product_code_extension_installed = True

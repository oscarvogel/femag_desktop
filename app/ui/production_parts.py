from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.models.masters import PRODUCT_KIND_PRODUCT, STOCK_ROLE_RAW, Product
from app.services.production_part_service import ProductionPartService
from app.services.stock_service import StockService
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


class ProductionPartPage(QWidget):
    """Produccion real por bolsas embolsadas (#580).

    No se piden kg de mandioca procesada ni de fecula producida: en planta esos
    datos no se pueden medir. Se carga cuantas bolsas de cada producto se
    embolsaron en el turno y los kg se derivan del peso del producto.

    Desde #730 el parte carga ademas **cuantos kilos de materia prima** consumio
    el turno. Las bolsas que entran al stock y el almidon que sale se escriben
    en la misma confirmacion: sin eso, el mismo kilo queda en los dos stocks.
    """

    HEADERS = (
        "Fecha", "Turno", "Estado", "Productos", "Bolsas", "Kg embolsados",
        "Kg consumidos", "Observación",
    )
    LINE_HEADERS = ("Producto", "Bolsas", "Kg embolsados")
    CONSUMPTION_HEADERS = ("Materia prima", "Kg consumidos", "Disponible en stock")

    def __init__(self, parent=None, *, service=None, current_username: str | None = None):
        super().__init__(parent)
        self.service = service or ProductionPartService()
        self.current_username = current_username
        self.rows = []
        self.editing_part = None
        self.pending = []
        self.pending_consumptions = []
        # Antes de _build_ui: el combo ya dispara currentIndexChanged al
        # agregar el primer producto y el slot consulta este diccionario.
        self._products_by_id = {}
        self._raw_materials_by_id = {}
        self._build_ui()
        self._load_products()
        self._load_raw_materials()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel("Partes de producción")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Cargá cuántas bolsas de cada producto se embolsaron en el turno. "
            "Los kg se calculan con el peso de cada bolsa. No se asignan camiones "
            "ni tickets individuales. Cargá también los kilos de materia prima que "
            "consumió el turno: al confirmar, las bolsas entran al stock y el "
            "almidón sale."
        )
        subheading.setObjectName("subheading")
        layout.addWidget(subheading)

        form = QFormLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("productionPartDay")
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.dateChanged.connect(self._day_changed)
        self.shift = QComboBox()
        self.shift.setEditable(True)
        self.shift.addItems(["Mañana", "Tarde", "Noche"])
        self.observations = QLineEdit()
        form.addRow("Fecha", self.day)
        form.addRow("Turno", self.shift)
        form.addRow("Observación", self.observations)
        layout.addLayout(form)

        lines_heading = QLabel("Productos embolsados")
        lines_heading.setObjectName("subheading")
        layout.addWidget(lines_heading)

        picker = QHBoxLayout()
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("productionPartProductCombo")
        enable_combo_autocomplete(self.product_combo)
        self.product_combo.currentIndexChanged.connect(self._sync_product_weight)
        self.bags_input = QSpinBox()
        self.bags_input.setObjectName("productionPartBagsInput")
        self.bags_input.setRange(1, 9_999_999)
        self.bags_input.setValue(1)
        self.bags_input.setSuffix(" bolsas")
        add_button = QPushButton("Agregar producto")
        add_button.setObjectName("productionPartAddProductButton")
        add_button.clicked.connect(self._add_line)
        picker.addWidget(self.product_combo, 2)
        picker.addWidget(self.bags_input)
        picker.addWidget(add_button)
        layout.addLayout(picker)

        self.weight_hint = QLabel()
        self.weight_hint.setObjectName("subheading")
        layout.addWidget(self.weight_hint)

        self.lines_table = QTableWidget(0, len(self.LINE_HEADERS))
        self.lines_table.setObjectName("productionPartLinesTable")
        self.lines_table.setHorizontalHeaderLabels(self.LINE_HEADERS)
        self.lines_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lines_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.lines_table, 1)

        remove_button = QPushButton("Quitar producto seleccionado")
        remove_button.setObjectName("productionPartRemoveProductButton")
        remove_button.clicked.connect(self._remove_line)
        remove_layout = QHBoxLayout()
        remove_layout.addWidget(remove_button)
        remove_layout.addStretch(1)
        layout.addLayout(remove_layout)

        # Materia prima consumida (#730). Va despues de las bolsas porque es
        # el otro lado de la misma confirmacion: las bolsas entran al stock y
        # el almidon sale.
        consumption_heading = QLabel("Materia prima consumida")
        consumption_heading.setObjectName("subheading")
        layout.addWidget(consumption_heading)

        consumption_picker = QHBoxLayout()
        self.raw_material_combo = QComboBox()
        self.raw_material_combo.setObjectName("productionPartRawMaterialCombo")
        enable_combo_autocomplete(self.raw_material_combo)
        self.raw_material_combo.currentIndexChanged.connect(self._sync_raw_material_stock)
        self.consumed_kg_input = QDoubleSpinBox()
        self.consumed_kg_input.setObjectName("productionPartConsumedKgInput")
        self.consumed_kg_input.setRange(0.01, 9_999_999.99)
        self.consumed_kg_input.setDecimals(2)
        self.consumed_kg_input.setSuffix(" kg")
        self.consumed_kg_input.setValue(1000.0)
        add_consumption_button = QPushButton("Agregar materia prima")
        add_consumption_button.setObjectName("productionPartAddConsumptionButton")
        add_consumption_button.clicked.connect(self._add_consumption)
        consumption_picker.addWidget(self.raw_material_combo, 2)
        consumption_picker.addWidget(self.consumed_kg_input)
        consumption_picker.addWidget(add_consumption_button)
        layout.addLayout(consumption_picker)

        self.consumption_hint = QLabel()
        self.consumption_hint.setObjectName("subheading")
        layout.addWidget(self.consumption_hint)

        self.consumptions_table = QTableWidget(0, len(self.CONSUMPTION_HEADERS))
        self.consumptions_table.setObjectName("productionPartConsumptionsTable")
        self.consumptions_table.setHorizontalHeaderLabels(self.CONSUMPTION_HEADERS)
        self.consumptions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.consumptions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.consumptions_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.consumptions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.consumptions_table, 1)

        remove_consumption_button = QPushButton("Quitar materia prima seleccionada")
        remove_consumption_button.setObjectName("productionPartRemoveConsumptionButton")
        remove_consumption_button.clicked.connect(self._remove_consumption)
        consumption_actions = QHBoxLayout()
        consumption_actions.addWidget(remove_consumption_button)
        consumption_actions.addStretch(1)
        layout.addLayout(consumption_actions)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Guardar parte")
        self.save_button.setObjectName("productionPartSaveButton")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancelar modificación")
        self.cancel_button.setObjectName("productionPartCancelButton")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_edit)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("productionPartTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.itemSelectionChanged.connect(self._sync_row_buttons)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        row_actions = QHBoxLayout()
        self.edit_button = QPushButton("Modificar")
        self.edit_button.setObjectName("productionPartEditButton")
        self.edit_button.clicked.connect(self.edit_selected)
        self.confirm_button = QPushButton("Confirmar parte")
        self.confirm_button.setObjectName("productionPartConfirmButton")
        self.confirm_button.clicked.connect(self.confirm_selected)
        self.annul_button = QPushButton("Anular")
        self.annul_button.setObjectName("productionPartAnnulButton")
        self.annul_button.clicked.connect(self.annul_selected)
        row_actions.addWidget(self.edit_button)
        row_actions.addWidget(self.confirm_button)
        row_actions.addWidget(self.annul_button)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        self.feedback = FormFeedback("productionPartFeedback")
        layout.addWidget(self.feedback)

    def _load_products(self):
        # Solo productos de venta: lo que se embolsa es lo que se despacha, no un
        # servicio, un interno o un articulo todavia en revision. El mismo criterio
        # que usa el maestro para marcar un producto como cargable.
        products = list(
            Product.select()
            .where(
                (Product.active == True)  # noqa: E712
                & (Product.peso_unitario_kg > 0)
                & (Product.product_kind == PRODUCT_KIND_PRODUCT)
            )
            .order_by(Product.name)
        )
        for product in products:
            self.product_combo.addItem(product.name, product.id)
        self._products_by_id = {product.id: product for product in products}
        self._sync_product_weight()

    def _sync_product_weight(self):
        product = self._current_product()
        if product is None:
            self.weight_hint.setText(
                "No hay productos de venta activos con peso de bolsa cargado. "
                "Cargalo en Maestros > Productos, columna «Peso» (campo «Peso unitario» "
                "del alta o la edicion) antes de registrar bolsas."
            )
            return
        self.weight_hint.setText(
            f"Peso por bolsa de «{product.name}»: {product.peso_unitario_kg:,.3f} kg · "
            f"{product.unit}"
        )

    def _load_raw_materials(self):
        """Materias primas que el turno puede consumir.

        El filtro es **exactamente el mismo** que usa la pantalla de Ingreso de
        materia prima (#656): lo que se puede comprar es lo que se puede
        consumir. Si los dos filtros se separaran, el operador podria
        consumir algo que no se puede recibir.
        """
        products = list(
            Product.select()
            .where(
                (Product.active == True)  # noqa: E712
                & (Product.peso_unitario_kg > 0)
                & (Product.stock_role == STOCK_ROLE_RAW)
            )
            .order_by(Product.name)
        )
        for product in products:
            self.raw_material_combo.addItem(product.name, product.id)
        self._raw_materials_by_id = {product.id: product for product in products}
        self._sync_raw_material_stock()

    def _current_raw_material(self):
        product_id = self.raw_material_combo.currentData()
        return self._raw_materials_by_id.get(product_id) if product_id else None

    def _sync_raw_material_stock(self):
        """Muestra el stock disponible de la materia prima elegida.

        El disponible sale del libro de movimientos, asi que ya descuenta lo que
        consumieron los partes anteriores. Se muestra **antes** de elegir, para
        que el operador no se lleve la sorpresa al confirmar: si no alcanza,
        la confirmacion se bloquea (#730).
        """
        self._update_consumption_hint()

    def _update_consumption_hint(self):
        """El hint junta las dos cosas que el operador necesita ver.

        Cuanto hay disponible de la materia prima que esta seleccionada, y
        cuanto lleva cargado de este turno. Antes de #730 la parte no tenia
        nada de esto: el consumo aparecia recien al confirmar.
        """
        producto = self._current_raw_material()
        if producto is None:
            self.consumption_hint.setText(
                "No hay materias primas activas con peso de big bag cargado. Cargalo en "
                "Maestros > Productos con «Rol en el stock» = Materia prima y el peso "
                "del big bag en «Peso unitario»."
            )
            return
        disponible = StockService.balance_for(producto).balance_kg
        total = sum((kg for _, kg in self.pending_consumptions), 0.0)
        self.consumption_hint.setText(
            f"Disponible de «{producto.name}»: {disponible:,.3f} kg en stock · "
            f"{len(self.pending_consumptions)} materia(s) cargada(s) · "
            f"{total:,.2f} kg consumidos"
        )

    def _add_consumption(self):
        product = self._current_raw_material()
        if product is None:
            self.feedback.show_warning(
                "Seleccione una materia prima con peso de big bag cargado."
            )
            return
        kg = float(self.consumed_kg_input.value())
        if kg <= 0:
            self.feedback.show_warning("Los kilos consumidos deben ser mayores a cero.")
            return
        if any(existing.id == product.id for existing, _ in self.pending_consumptions):
            self.feedback.show_warning(
                f"«{product.name}» ya está cargado como materia prima en este turno."
            )
            return
        self.pending_consumptions.append((product, kg))
        self._render_consumptions()

    def _remove_consumption(self):
        index = self.consumptions_table.currentRow()
        if index < 0 or index >= len(self.pending_consumptions):
            self.feedback.show_warning("Seleccione una línea para quitar.")
            return
        removed = self.pending_consumptions.pop(index)[0]
        self._render_consumptions()
        self.feedback.show_info(f"«{removed.name}» quitado del consumo.")

    def _render_consumptions(self):
        self.consumptions_table.setRowCount(len(self.pending_consumptions))
        for index, (product, kg) in enumerate(self.pending_consumptions):
            disponible = StockService.balance_for(product).balance_kg
            values = (product.name, f"{kg:,.2f}", f"{disponible:,.3f}")
            for column, value in enumerate(values):
                self.consumptions_table.setItem(index, column, QTableWidgetItem(str(value)))
        self._update_consumption_hint()

    def _current_product(self):
        product_id = self.product_combo.currentData()
        return self._products_by_id.get(product_id) if product_id else None

    def _kg_preview(self, product, bags):
        return product.peso_unitario_kg * bags

    def _add_line(self):
        product = self._current_product()
        if product is None:
            self.feedback.show_warning("Seleccione un producto con peso de bolsa cargado.")
            return
        bags = int(self.bags_input.value())
        if any(existing.id == product.id for existing, _ in self.pending):
            self.feedback.show_warning(f"«{product.name}» ya está cargado en este turno.")
            return
        self.pending.append((product, bags))
        self._render_lines()
        self.feedback.show_info(f"«{product.name}» agregado. Guardá el parte para confirmarlo.")

    def _remove_line(self):
        index = self.lines_table.currentRow()
        if index < 0 or index >= len(self.pending):
            self.feedback.show_warning("Seleccione una línea para quitar.")
            return
        removed = self.pending.pop(index)[0]
        self._render_lines()
        self.feedback.show_info(f"«{removed.name}» quitado del parte.")

    def _render_lines(self):
        self.lines_table.setRowCount(len(self.pending))
        for index, (product, bags) in enumerate(self.pending):
            values = (product.name, f"{bags:,}", f"{self._kg_preview(product, bags):,.2f}")
            for column, value in enumerate(values):
                self.lines_table.setItem(index, column, QTableWidgetItem(str(value)))
        total_kg = sum((self._kg_preview(p, b) for p, b in self.pending), start=0)
        self.weight_hint.setText(
            f"{len(self.pending)} producto(s) · {sum(b for _, b in self.pending):,} bolsa(s) · "
            f"{total_kg:,.2f} kg embolsados"
        )

    def selected_date(self):
        return self.day.date().toPyDate()

    def _day_changed(self):
        self.cancel_edit()
        self.refresh()

    def refresh(self):
        self.rows = self.service.for_day(self.selected_date())
        totals = self.service.totals(self.rows)
        confirmados = sum(1 for row in self.rows if row.is_confirmed and not row.is_voided)
        pendientes = sum(
            1 for row in self.rows if not row.is_confirmed and not row.is_voided
        )
        self.summary.setText(
            f"{totals.parts} parte(s) del {self.selected_date():%d/%m/%Y} · "
            f"{confirmados} confirmado(s) · {pendientes} en borrador · "
            f"{totals.lines} producto(s) · {totals.bags:,} bolsa(s) · "
            f"{totals.kg:,.2f} kg embolsados · "
            f"{totals.consumed_kg:,.2f} kg de materia prima consumidos"
        )
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            bags = sum((int(bag.bags or 0) for bag in self.service.lines_of(row)), 0)
            kg = sum((float(bag.kg or 0) for bag in self.service.lines_of(row)), 0.0)
            consumido = sum(
                (float(consumo.kg or 0) for consumo in self.service.consumptions_of(row)), 0.0
            )
            values = (
                row.production_date.strftime("%d/%m/%Y"), row.shift,
                row.status_label,
                len(self.service.lines_of(row)), f"{bags:,}", f"{kg:,.2f}",
                f"{consumido:,.2f}",
                row.observations or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self._sync_row_buttons()

    def _selected_part(self, *, avisar: bool = True):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            if avisar:
                self.feedback.show_warning("Seleccione un parte.")
            return None
        return self.rows[index]

    def _sync_row_buttons(self):
        """Cada boton segun el estado del parte elegido.

        Borrador: se edita, se confirma y se borra.
        Confirmado: ya esta en el stock, no se toca; solo se anula con motivo.
        Anulado: no se toca mas.
        """
        part = self._selected_part(avisar=False)
        hay_seleccion = part is not None
        es_borrador = hay_seleccion and not part.is_confirmed and not part.is_voided
        self.edit_button.setEnabled(es_borrador)
        self.confirm_button.setEnabled(es_borrador)
        self.annul_button.setEnabled(hay_seleccion and not part.is_voided)

    def edit_selected(self):
        part = self._selected_part()
        if part is None:
            return
        self.editing_part = part
        self.shift.setCurrentText(part.shift)
        self.observations.setText(part.observations or "")
        self.pending = [(bag.product, int(bag.bags)) for bag in self.service.lines_of(part)]
        self.pending_consumptions = [
            (consumo.product, float(consumo.kg or 0))
            for consumo in self.service.consumptions_of(part)
        ]
        self._render_lines()
        self._render_consumptions()
        self.save_button.setText("Guardar modificación")
        self.cancel_button.setVisible(True)
        self.feedback.show_info("Modificá los datos y guardá los cambios.")

    def cancel_edit(self):
        self.editing_part = None
        self.pending = []
        self.pending_consumptions = []
        self.save_button.setText("Guardar parte")
        self.cancel_button.setVisible(False)
        self.observations.clear()
        self.bags_input.setValue(1)
        self.consumed_kg_input.setValue(1000.0)
        self._render_lines()
        self._render_consumptions()
        self._sync_product_weight()
        self._sync_raw_material_stock()

    def save(self):
        try:
            if self.editing_part is None:
                part = self.service.create(
                    production_date=self.selected_date(), shift=self.shift.currentText(),
                    lines=self.pending, consumptions=self.pending_consumptions,
                    observations=self.observations.text(),
                )
                message = "Parte guardado."
            else:
                part = self.service.update(
                    self.editing_part, production_date=self.selected_date(),
                    shift=self.shift.currentText(), lines=self.pending,
                    consumptions=self.pending_consumptions,
                    observations=self.observations.text(),
                )
                message = "Parte modificado."
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        totals = self.service.totals([part])
        self.cancel_edit()
        self.refresh()
        self.feedback.show_success(
            f"{message} {totals.bags:,} bolsa(s) · {totals.kg:,.2f} kg embolsados · "
            f"{totals.consumed_kg:,.2f} kg de materia prima consumidos."
        )

    def confirm_selected(self):
        """El operador confirma el turno: la produccion entra al stock y la
        materia prima consumida sale."""
        part = self._selected_part()
        if part is None:
            return
        lineas = self.service.lines_of(part)
        kg = sum((float(bag.kg or 0) for bag in lineas), 0.0)
        consumos = self.service.consumptions_of(part)
        consumos_kg = sum((float(consumo.kg or 0) for consumo in consumos), 0.0)
        detalle_consumo = "\n".join(
            f"· {consumo.product.name}: {float(consumo.kg or 0):,.2f} kg"
            for consumo in consumos
        )
        answer = QMessageBox.question(
            self, "Confirmar parte",
            f"Confirmar el parte del {part.production_date:%d/%m/%Y} - {part.shift}?\n\n"
            f"{len(lineas)} producto(s) · {kg:,.2f} kg.\n\n"
            f"Materia prima consumida ({consumos_kg:,.2f} kg):\n{detalle_consumo}\n\n"
            "Al confirmar, la producción entra al stock y la materia prima sale. "
            "El parte ya no se puede editar: solo se anula con motivo, generando "
            "el movimiento contrario.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.confirm(part, current_user=self.current_username)
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        self.cancel_edit()
        self.refresh()
        self.feedback.show_success(
            f"Parte confirmado: {kg:,.2f} kg entraron al stock y "
            f"{consumos_kg:,.2f} kg de materia prima salieron."
        )

    def annul_selected(self):
        part = self._selected_part()
        if part is None:
            return

        motivo = ""
        if part.is_confirmed:
            motivo, acepto = QInputDialog.getText(
                self, "Anular parte confirmado",
                "El parte ya está confirmado y su producción está en el stock.\n"
                "Se van a generar los movimientos contrarios y queda asentado "
                "quién lo anuló y por qué.\n\nMotivo:",
            )
            if not acepto:
                return
            motivo = (motivo or "").strip()
            if not motivo:
                self.feedback.show_warning("El motivo es obligatorio.")
                return
        else:
            answer = QMessageBox.question(
                self, "Anular parte",
                f"¿Anular el parte del {part.production_date:%d/%m/%Y} - {part.shift}?\n\n"
                "Está en borrador: se borra sin dejar rastro porque todavía no "
                "tocó el stock.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            self.service.annul(part, current_user=self.current_username, reason=motivo)
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        self.cancel_edit()
        self.refresh()
        if part.is_confirmed:
            self.feedback.show_success(
                "Parte anulado: se generaron los movimientos contrarios en el stock."
            )
        else:
            self.feedback.show_success("Parte anulado.")

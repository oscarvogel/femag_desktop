from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.models.masters import Product
from app.services.production_part_service import ProductionPartService
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


class ProductionPartPage(QWidget):
    """Produccion real por bolsas embolsadas (#580).

    No se piden kg de mandioca procesada ni de fecula producida: en planta esos
    datos no se pueden medir. Se carga cuantas bolsas de cada producto se
    embolsaron en el turno y los kg se derivan del peso del producto.
    """

    HEADERS = ("Fecha", "Turno", "Productos", "Bolsas", "Kg embolsados", "Observación")
    LINE_HEADERS = ("Producto", "Bolsas", "Kg embolsados")

    def __init__(self, parent=None, *, service=None):
        super().__init__(parent)
        self.service = service or ProductionPartService()
        self.rows = []
        self.editing_part = None
        self.pending = []
        # Antes de _build_ui: el combo ya dispara currentIndexChanged al
        # agregar el primer producto y el slot consulta este diccionario.
        self._products_by_id = {}
        self._build_ui()
        self._load_products()
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
            "ni tickets individuales."
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
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        row_actions = QHBoxLayout()
        self.edit_button = QPushButton("Modificar")
        self.edit_button.setObjectName("productionPartEditButton")
        self.edit_button.clicked.connect(self.edit_selected)
        self.annul_button = QPushButton("Anular")
        self.annul_button.setObjectName("productionPartAnnulButton")
        self.annul_button.clicked.connect(self.annul_selected)
        row_actions.addWidget(self.edit_button)
        row_actions.addWidget(self.annul_button)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        self.feedback = FormFeedback("productionPartFeedback")
        layout.addWidget(self.feedback)

    def _load_products(self):
        products = list(
            Product.select()
            .where((Product.active == True) & (Product.peso_unitario_kg > 0))  # noqa: E712
            .order_by(Product.name)
        )
        for product in products:
            self.product_combo.addItem(product.name, product.id)
        self._products_by_id = {product.id: product for product in products}
        self._sync_product_weight()

    def _sync_product_weight(self):
        product = self._current_product()
        if product is None:
            self.weight_hint.setText("No hay productos activos con peso de bolsa cargado.")
            return
        self.weight_hint.setText(
            f"Peso por bolsa de «{product.name}»: {product.peso_unitario_kg:,.3f} kg · "
            f"{product.unit}"
        )

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
        self.summary.setText(
            f"{totals.parts} parte(s) del {self.selected_date():%d/%m/%Y} · "
            f"{totals.lines} producto(s) · {totals.bags:,} bolsa(s) · "
            f"{totals.kg:,.2f} kg embolsados"
        )
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            bags = sum((int(bag.bags or 0) for bag in self.service.lines_of(row)), 0)
            kg = sum((float(bag.kg or 0) for bag in self.service.lines_of(row)), 0.0)
            values = (
                row.production_date.strftime("%d/%m/%Y"), row.shift,
                len(self.service.lines_of(row)), f"{bags:,}", f"{kg:,.2f}",
                row.observations or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        enabled = bool(self.rows)
        self.edit_button.setEnabled(enabled)
        self.annul_button.setEnabled(enabled)

    def _selected_part(self):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            self.feedback.show_warning("Seleccione un parte.")
            return None
        return self.rows[index]

    def edit_selected(self):
        part = self._selected_part()
        if part is None:
            return
        self.editing_part = part
        self.shift.setCurrentText(part.shift)
        self.observations.setText(part.observations or "")
        self.pending = [(bag.product, int(bag.bags)) for bag in self.service.lines_of(part)]
        self._render_lines()
        self.save_button.setText("Guardar modificación")
        self.cancel_button.setVisible(True)
        self.feedback.show_info("Modificá los datos y guardá los cambios.")

    def cancel_edit(self):
        self.editing_part = None
        self.pending = []
        self.save_button.setText("Guardar parte")
        self.cancel_button.setVisible(False)
        self.observations.clear()
        self.bags_input.setValue(1)
        self._render_lines()
        self._sync_product_weight()

    def save(self):
        try:
            if self.editing_part is None:
                part = self.service.create(
                    production_date=self.selected_date(), shift=self.shift.currentText(),
                    lines=self.pending, observations=self.observations.text(),
                )
                message = "Parte guardado."
            else:
                part = self.service.update(
                    self.editing_part, production_date=self.selected_date(),
                    shift=self.shift.currentText(), lines=self.pending,
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
            f"{message} {totals.bags:,} bolsa(s) · {totals.kg:,.2f} kg embolsados."
        )

    def annul_selected(self):
        part = self._selected_part()
        if part is None:
            return
        answer = QMessageBox.question(
            self, "Anular parte",
            f"¿Anular el parte del {part.production_date:%d/%m/%Y} - {part.shift}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.service.annul(part)
        self.cancel_edit()
        self.refresh()
        self.feedback.show_success("Parte anulado.")

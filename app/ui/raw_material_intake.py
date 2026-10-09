from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.models.masters import STOCK_ROLE_RAW, Product
from app.services.raw_material_intake_service import RawMaterialIntakeService
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


class RawMaterialIntakePage(QWidget):
    """Ingreso de materia prima comprada en big bags (#656).

    Se cuentan big bags, no kilos: en planta el almidon suelto no se pesa, se
    cuentan las unidades que llegan. Los kg salen del peso del big bag, que se
    congela al registrar la linea. Confirmar el ingreso lo mete al stock como
    movimiento de compra; anularlo genera el movimiento contrario.
    """

    HEADERS = ("Fecha", "Estado", "Materias", "Big bags", "Kg ingresados", "Observación")
    LINE_HEADERS = ("Materia prima", "Big bags", "Kg por big bag", "Kg de la línea")

    def __init__(self, parent=None, *, service=None, current_username: str | None = None):
        super().__init__(parent)
        self.service = service or RawMaterialIntakeService()
        self.current_username = current_username
        self.rows = []
        self.editing_intake = None
        self.pending = []
        # Antes de _build_ui: el combo ya dispara currentIndexChanged al agregar
        # el primer producto y el slot consulta este diccionario.
        self._products_by_id = {}
        self._build_ui()
        self._load_products()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel("Ingreso de materia prima")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Cargá los big bags de almidón u otra materia prima que llegan. "
            "Al confirmar el ingreso, la materia prima entra al stock y después "
            "se puede fraccionar en bolsas."
        )
        subheading.setObjectName("subheading")
        layout.addWidget(subheading)

        form = QFormLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setObjectName("rawMaterialIntakeDay")
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.day.dateChanged.connect(self._day_changed)
        self.observations = QLineEdit()
        self.observations.setObjectName("rawMaterialIntakeObservations")
        self.observations.setPlaceholderText(
            "Opcional. Anotá el proveedor mientras no exista el maestro de proveedores."
        )
        form.addRow("Fecha de ingreso", self.day)
        form.addRow("Observación", self.observations)
        layout.addLayout(form)

        lines_heading = QLabel("Big bags que ingresan")
        lines_heading.setObjectName("subheading")
        layout.addWidget(lines_heading)

        picker = QHBoxLayout()
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("rawMaterialIntakeProductCombo")
        enable_combo_autocomplete(self.product_combo)
        self.product_combo.currentIndexChanged.connect(self._sync_product_weight)
        self.bags_input = QSpinBox()
        self.bags_input.setObjectName("rawMaterialIntakeBagsInput")
        self.bags_input.setRange(1, 9_999_999)
        self.bags_input.setValue(1)
        self.bags_input.setSuffix(" big bags")
        add_button = QPushButton("Agregar materia prima")
        add_button.setObjectName("rawMaterialIntakeAddProductButton")
        add_button.clicked.connect(self._add_line)
        picker.addWidget(self.product_combo, 2)
        picker.addWidget(self.bags_input)
        picker.addWidget(add_button)
        layout.addLayout(picker)

        self.weight_hint = QLabel()
        self.weight_hint.setObjectName("subheading")
        self.weight_hint.setWordWrap(True)
        layout.addWidget(self.weight_hint)

        self.lines_table = QTableWidget(0, len(self.LINE_HEADERS))
        self.lines_table.setObjectName("rawMaterialIntakeLinesTable")
        self.lines_table.setHorizontalHeaderLabels(self.LINE_HEADERS)
        self.lines_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.lines_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.lines_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.lines_table, 1)

        remove_button = QPushButton("Quitar materia prima seleccionada")
        remove_button.setObjectName("rawMaterialIntakeRemoveProductButton")
        remove_button.clicked.connect(self._remove_line)
        remove_layout = QHBoxLayout()
        remove_layout.addWidget(remove_button)
        remove_layout.addStretch(1)
        layout.addLayout(remove_layout)

        actions = QHBoxLayout()
        self.save_button = QPushButton("Guardar ingreso")
        self.save_button.setObjectName("rawMaterialIntakeSaveButton")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.cancel_button = QPushButton("Cancelar modificación")
        self.cancel_button.setObjectName("rawMaterialIntakeCancelButton")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_edit)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("rawMaterialIntakeTable")
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
        self.edit_button.setObjectName("rawMaterialIntakeEditButton")
        self.edit_button.clicked.connect(self.edit_selected)
        self.confirm_button = QPushButton("Confirmar ingreso")
        self.confirm_button.setObjectName("rawMaterialIntakeConfirmButton")
        self.confirm_button.clicked.connect(self.confirm_selected)
        self.annul_button = QPushButton("Anular")
        self.annul_button.setObjectName("rawMaterialIntakeAnnulButton")
        self.annul_button.clicked.connect(self.annul_selected)
        row_actions.addWidget(self.edit_button)
        row_actions.addWidget(self.confirm_button)
        row_actions.addWidget(self.annul_button)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)

        self.feedback = FormFeedback("rawMaterialIntakeFeedback")
        layout.addWidget(self.feedback)

    def _load_products(self):
        # Solo materia prima activa con peso de big bag cargado: lo que se
        # fracciona es lo que se compra en big bags, no un producto que se vende
        # tal cual ni un artículo sin peso cargado.
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
            self.product_combo.addItem(product.name, product.id)
        self._products_by_id = {product.id: product for product in products}
        self._sync_product_weight()

    def _sync_product_weight(self):
        product = self._current_product()
        if product is None:
            self.weight_hint.setText(
                "No hay materias primas activas con peso de big bag cargado. "
                "En Maestros > Productos, poné «Rol en el stock» = Materia prima y "
                "cargá el peso de un big bag en «Peso unitario»."
            )
            return
        self.weight_hint.setText(
            f"Peso por big bag de «{product.name}»: {product.peso_unitario_kg:,.3f} kg"
        )

    def _current_product(self):
        product_id = self.product_combo.currentData()
        return self._products_by_id.get(product_id) if product_id else None

    def _kg_preview(self, product, bags):
        return product.peso_unitario_kg * bags

    def _add_line(self):
        product = self._current_product()
        if product is None:
            self.feedback.show_warning("Seleccione una materia prima con peso de big bag cargado.")
            return
        bags = int(self.bags_input.value())
        if any(existing.id == product.id for existing, _ in self.pending):
            self.feedback.show_warning(f"«{product.name}» ya está cargado en este ingreso.")
            return
        self.pending.append((product, bags))
        self._render_lines()
        self.feedback.show_info(f"«{product.name}» agregado. Guardá el ingreso para confirmarlo.")

    def _remove_line(self):
        index = self.lines_table.currentRow()
        if index < 0 or index >= len(self.pending):
            self.feedback.show_warning("Seleccione una línea para quitar.")
            return
        removed = self.pending.pop(index)[0]
        self._render_lines()
        self.feedback.show_info(f"«{removed.name}» quitado del ingreso.")

    def _render_lines(self):
        self.lines_table.setRowCount(len(self.pending))
        for index, (product, bags) in enumerate(self.pending):
            values = (
                product.name, f"{bags:,}", f"{product.peso_unitario_kg:,.3f}",
                f"{self._kg_preview(product, bags):,.2f}",
            )
            for column, value in enumerate(values):
                self.lines_table.setItem(index, column, QTableWidgetItem(str(value)))
        total_bags = sum((bags for _, bags in self.pending), 0)
        total_kg = sum((self._kg_preview(p, b) for p, b in self.pending), start=0)
        if self.pending:
            self.weight_hint.setText(
                f"{len(self.pending)} tipo(s) de materia prima · {total_bags:,} big bag(s) · "
                f"{total_kg:,.2f} kg"
            )
        else:
            self._sync_product_weight()

    def selected_date(self):
        return self.day.date().toPyDate()

    def _day_changed(self):
        self.cancel_edit()
        self.refresh()

    def refresh(self):
        self.rows = self.service.for_day(self.selected_date())
        totals = self.service.totals(self.rows)
        confirmados = sum(1 for row in self.rows if row.is_confirmed and not row.is_voided)
        pendientes = sum(1 for row in self.rows if not row.is_confirmed and not row.is_voided)
        self.summary.setText(
            f"{totals.intakes} ingreso(s) del {self.selected_date():%d/%m/%Y} · "
            f"{confirmados} confirmado(s) · {pendientes} en borrador · "
            f"{totals.bags:,} big bag(s) · {totals.kg:,.2f} kg ingresados"
        )
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            lines = self.service.lines_of(row)
            bags = sum((int(line.bags or 0) for line in lines), 0)
            kg = sum((float(line.kg or 0) for line in lines), 0.0)
            values = (
                row.received_at.strftime("%d/%m/%Y"), row.status_label,
                len(lines), f"{bags:,}", f"{kg:,.2f}", row.observations or "",
            )
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self._sync_row_buttons()

    def _selected_intake(self, *, avisar: bool = True):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.rows):
            if avisar:
                self.feedback.show_warning("Seleccione un ingreso.")
            return None
        return self.rows[index]

    def _sync_row_buttons(self):
        """Cada boton segun el estado del ingreso elegido.

        Borrador: se edita, se confirma y se borra.
        Confirmado: ya esta en el stock, no se toca; solo se anula con motivo.
        Anulado: no se toca mas.
        """
        intake = self._selected_intake(avisar=False)
        hay_seleccion = intake is not None
        es_borrador = hay_seleccion and not intake.is_confirmed and not intake.is_voided
        self.edit_button.setEnabled(es_borrador)
        self.confirm_button.setEnabled(es_borrador)
        self.annul_button.setEnabled(hay_seleccion and not intake.is_voided)

    def edit_selected(self):
        intake = self._selected_intake()
        if intake is None:
            return
        self.editing_intake = intake
        self.observations.setText(intake.observations or "")
        self.pending = [
            (line.product, int(line.bags)) for line in self.service.lines_of(intake)
        ]
        self._render_lines()
        self.save_button.setText("Guardar modificación")
        self.cancel_button.setVisible(True)
        self.feedback.show_info("Modificá los datos y guardá los cambios.")

    def cancel_edit(self):
        self.editing_intake = None
        self.pending = []
        self.save_button.setText("Guardar ingreso")
        self.cancel_button.setVisible(False)
        self.observations.clear()
        self.bags_input.setValue(1)
        self._render_lines()
        self._sync_product_weight()

    def save(self):
        try:
            if self.editing_intake is None:
                intake = self.service.create(
                    received_at=self.selected_date(), lines=self.pending,
                    observations=self.observations.text(),
                )
                message = "Ingreso guardado."
            else:
                intake = self.service.update(
                    self.editing_intake, received_at=self.selected_date(),
                    lines=self.pending, observations=self.observations.text(),
                )
                message = "Ingreso modificado."
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        totals = self.service.totals([intake])
        self.cancel_edit()
        self.refresh()
        self.feedback.show_success(
            f"{message} {totals.bags:,} big bag(s) · {totals.kg:,.2f} kg."
        )

    def confirm_selected(self):
        """El operador confirma el ingreso y la materia prima entra al stock."""
        intake = self._selected_intake()
        if intake is None:
            return
        lines = self.service.lines_of(intake)
        bags = sum((int(line.bags or 0) for line in lines), 0)
        kg = sum((float(line.kg or 0) for line in lines), 0.0)
        answer = QMessageBox.question(
            self, "Confirmar ingreso",
            f"Confirmar el ingreso del {intake.received_at:%d/%m/%Y}?\n\n"
            f"{len(lines)} materia(s) prima(s) · {bags:,} big bag(s) · {kg:,.2f} kg.\n"
            "Al confirmar, la materia prima entra al stock y el ingreso ya no se "
            "puede editar: solo se anula con motivo, generando el movimiento "
            "contrario.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.confirm(intake, current_user=self.current_username)
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        self.cancel_edit()
        self.refresh()
        self.feedback.show_success(
            f"Ingreso confirmado: {kg:,.2f} kg entraron al stock."
        )

    def annul_selected(self):
        intake = self._selected_intake()
        if intake is None:
            return

        motivo = ""
        if intake.is_confirmed:
            motivo, acepto = QInputDialog.getText(
                self, "Anular ingreso confirmado",
                "El ingreso ya está confirmado y su materia prima está en el stock.\n"
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
                self, "Anular ingreso",
                f"¿Anular el ingreso del {intake.received_at:%d/%m/%Y}?\n\n"
                "Está en borrador: se borra sin dejar rastro porque todavía no "
                "tocó el stock.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            self.service.annul(intake, current_user=self.current_username, reason=motivo)
        except Exception as exc:
            self.feedback.show_error(str(exc))
            return
        self.cancel_edit()
        self.refresh()
        if intake.is_confirmed:
            self.feedback.show_success(
                "Ingreso anulado: se generaron los movimientos contrarios en el stock."
            )
        else:
            self.feedback.show_success("Ingreso anulado.")

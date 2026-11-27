"""Pantalla "Maestros > Productores" (#963).

ABM de la persona productora: nombre, contacto, CUIT/DNI y la marca de
identidad verificada. Reutiliza la tabla con busqueda y orden de los otros
maestros (``MasterTableController``) y sus permisos (``Maestros`` /
``Productores``: ver, crear, modificar).
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app.models.suppliers import Supplier, SupplierLegacyCode
from app.services.supplier_master_service import (
    MENU_SECTION,
    MENU_TITLE,
    SupplierMasterError,
    SupplierMasterService,
    format_tax_id,
)
from app.ui.form_feedback import FormFeedback
from app.ui.master_abm import (
    MasterTableController,
    _action_button,
    _can_use_menu_action,
    _entry_feedback,
    _entry_footer,
    _entry_layout,
    _page,
    enable_master_activation,
)
from app.ui.supplier_payment_dialog import format_money

COLUMNS = [
    "Nombre",
    "Códigos legacy",
    "Localidad",
    "Teléfono",
    "CUIT/DNI",
    "Identidad",
    "Estado",
]


class SupplierEntryDialog(QDialog):
    def __init__(self, *, current_user: str, record_id: int | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.record_id = record_id
        self.saved_record: Supplier | None = None
        self.setObjectName("supplierEntryDialog")
        self.setWindowTitle("Productor")
        self._build()
        self._load_record()

    def _build(self) -> None:
        layout = _entry_layout(self, "Productor")
        self.resize(560, 360)
        form = QGridLayout()
        self.name_input = QLineEdit()
        self.name_input.setObjectName("supplierNameInput")
        self.name_input.setMaxLength(80)
        self.tax_id_input = QLineEdit()
        self.tax_id_input.setObjectName("supplierTaxIdInput")
        self.tax_id_input.setPlaceholderText("CUIT (11 dígitos) o DNI (7 u 8)")
        self.locality_input = QLineEdit()
        self.locality_input.setObjectName("supplierLocalityInput")
        self.locality_input.setMaxLength(40)
        self.phone_input = QLineEdit()
        self.phone_input.setObjectName("supplierPhoneInput")
        self.phone_input.setMaxLength(40)
        self.verified_check = QCheckBox("Identidad verificada (la planta conoce al productor)")
        self.verified_check.setObjectName("supplierVerifiedCheck")
        self.notes_input = QPlainTextEdit()
        self.notes_input.setObjectName("supplierNotesInput")
        self.notes_input.setFixedHeight(64)
        rows = (
            ("Nombre", self.name_input),
            ("CUIT/DNI", self.tax_id_input),
            ("Localidad", self.locality_input),
            ("Teléfono", self.phone_input),
            ("", self.verified_check),
            ("Observaciones", self.notes_input),
        )
        for index, (label, widget) in enumerate(rows):
            form.addWidget(QLabel(label), index, 0)
            form.addWidget(widget, index, 1)
        layout.addLayout(form)
        self.codes_label = QLabel()
        self.codes_label.setObjectName("supplierCodesLabel")
        self.codes_label.setWordWrap(True)
        self.codes_label.setStyleSheet("color:#64748b;")
        layout.addWidget(self.codes_label)
        self.feedback = _entry_feedback(layout)
        _entry_footer(layout, self, "saveSupplierButton", self._save)

    def _load_record(self) -> None:
        if self.record_id is None:
            self.codes_label.setText(
                "Productor nuevo: no tiene fichas del legacy. Si después se importa una "
                "ficha con el mismo nombre, se une a este productor."
            )
            return
        supplier = Supplier.get_by_id(self.record_id)
        self.name_input.setText(supplier.name)
        self.tax_id_input.setText(format_tax_id(supplier.tax_id))
        self.locality_input.setText(supplier.locality or "")
        self.phone_input.setText(supplier.phone or "")
        self.verified_check.setChecked(bool(supplier.identity_verified))
        self.notes_input.setPlainText(supplier.notes or "")
        codes = supplier.legacy_code_list
        self.codes_label.setText(
            f"Códigos del legacy: {', '.join(codes)}." if codes else "Sin fichas del legacy."
        )

    def _save(self) -> None:
        values = {
            "name": self.name_input.text(),
            "tax_id": self.tax_id_input.text(),
            "locality": self.locality_input.text(),
            "phone": self.phone_input.text(),
            "identity_verified": self.verified_check.isChecked(),
            "notes": self.notes_input.toPlainText(),
        }
        service = SupplierMasterService(self.current_user)
        try:
            if self.record_id is None:
                self.saved_record = service.create(**values)
            else:
                self.saved_record = service.update(
                    Supplier.get_by_id(self.record_id), **values
                )
        except SupplierMasterError as exc:
            self.feedback.show_warning(str(exc))
            return
        self.accept()


class SupplierDetailDialog(QDialog):
    """Ficha del productor: fichas del legacy y resumen de documentos y pagos."""

    def __init__(self, *, supplier_id: int, parent=None):
        super().__init__(parent)
        self.setObjectName("supplierDetailDialog")
        supplier = Supplier.get_by_id(supplier_id)
        self.setWindowTitle(f"Productor - {supplier.name}")
        layout = _entry_layout(self, supplier.name)
        self.resize(620, 420)
        identity = (
            f"CUIT/DNI {format_tax_id(supplier.tax_id)}" if supplier.tax_id else "Sin CUIT/DNI"
        )
        identity += " · verificada" if supplier.identity_verified else " · sin verificar"
        layout.addWidget(QLabel(identity))
        summary = SupplierMasterService.summary(supplier)
        self.summary_label = QLabel(
            f"Documentos importados: {summary.tickets} tickets y {summary.notes} pagarés "
            f"(saldo importado $ {format_money(summary.imported_balance)}). "
            f"Pagos registrados en FEMAG: {summary.payments}. "
            "El detalle está en Producción → Cuenta corriente productores."
        )
        self.summary_label.setObjectName("supplierDetailSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addWidget(QLabel("Fichas del legacy (femagfab.proveedo)"))
        fichas = list(supplier.legacy_code_rows.order_by(SupplierLegacyCode.code))
        self.codes_table = QTableWidget(len(fichas), 4)
        self.codes_table.setObjectName("supplierDetailCodes")
        self.codes_table.setHorizontalHeaderLabels(
            ["Código", "Nombre en el legacy", "Localidad", "Teléfono"]
        )
        self.codes_table.verticalHeader().setVisible(False)
        self.codes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.codes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for row, ficha in enumerate(fichas):
            for column, value in enumerate(
                (ficha.code, ficha.name, ficha.locality or "", ficha.phone or "")
            ):
                self.codes_table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(self.codes_table, 1)
        if len(fichas) > 1 and not supplier.identity_verified:
            # Es un aviso fijo de la ficha, no feedback de una accion: por eso
            # es un QLabel con el rol "notice" del tema y no un FormFeedback.
            unified_notice = QLabel(
                "Estas fichas se unieron porque tienen el mismo nombre. Confirme con el "
                "CUIT/DNI que son la misma persona y marque la identidad como verificada."
            )
            unified_notice.setObjectName("supplierDetailUnifiedNotice")
            unified_notice.setWordWrap(True)
            unified_notice.setProperty("uiRole", "notice")
            layout.addWidget(unified_notice)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = _action_button("closeSupplierDetailButton", "Cerrar", secondary=True)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)


def build_supplier_master_page(*, user, current_user: str, parent=None) -> QWidget:
    page = _page(
        "Productores",
        "Maestro de productores y colonos. El CUIT/DNI es lo que confirma la identidad "
        "de las fichas que el legacy unificó por nombre.",
    )
    page.setObjectName("supplierMasterPage")
    layout = page.layout()
    feedback = FormFeedback("supplierMasterFeedback")
    search_input = QLineEdit()
    search_input.setObjectName("supplierSearchInput")
    search_input.setClearButtonEnabled(True)
    search_input.setPlaceholderText("Buscar por nombre, código legacy o CUIT/DNI...")
    search_row = QHBoxLayout()
    search_row.addWidget(QLabel("Buscar"))
    search_row.addWidget(search_input, 1)
    layout.addLayout(search_row)
    search_feedback = FormFeedback("supplierSearchFeedback")
    layout.addWidget(search_feedback)

    can_create = _can_use_menu_action(user, MENU_SECTION, "crear", MENU_TITLE)
    can_modify = _can_use_menu_action(user, MENU_SECTION, "modificar", MENU_TITLE)
    actions = QHBoxLayout()
    new_button = _action_button("newSupplierButton", "Nuevo")
    edit_button = _action_button("editSupplierButton", "Editar", secondary=True)
    active_button = _action_button("toggleSupplierActiveButton", "Dar de baja", secondary=True)
    new_button.setEnabled(can_create)
    edit_button.setEnabled(can_modify)
    if not can_create:
        new_button.setToolTip("El perfil actual no permite crear productores.")
    if not can_modify:
        edit_button.setToolTip("El perfil actual no permite modificar productores.")
        active_button.setToolTip("El perfil actual no permite modificar productores.")
    for button in (new_button, edit_button, active_button):
        actions.addWidget(button)
    actions.addStretch(1)
    layout.addLayout(actions)

    table = QTableWidget(0, len(COLUMNS))
    table.setObjectName("supplierMasterTable")
    table.setHorizontalHeaderLabels(COLUMNS)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    layout.addWidget(table, 1)
    empty_label = QLabel(
        "No hay productores. Impórtelos desde Producción → Cuenta corriente productores "
        "o cree uno nuevo."
    )
    empty_label.setObjectName("supplierMasterEmpty")
    layout.addWidget(empty_label)
    layout.addWidget(feedback)

    controller = MasterTableController(
        table=table,
        search_input=search_input,
        search_feedback=search_feedback,
        rows_fn=SupplierMasterService.rows,
    )

    def selected() -> Supplier | None:
        row_id = controller.selected_id()
        return Supplier.get_or_none(Supplier.id == row_id) if row_id is not None else None

    def sync_actions(*_args) -> None:
        supplier = selected()
        active_button.setText("Reactivar" if supplier is not None and not supplier.active else "Dar de baja")
        active_button.setEnabled(can_modify and supplier is not None)
        edit_button.setEnabled(can_modify and supplier is not None)
        empty_label.setVisible(table.rowCount() == 0 and not search_input.text().strip())

    def refresh(*_args) -> None:
        controller.refresh()
        sync_actions()

    def open_new() -> None:
        if not can_create:
            feedback.show_warning("El perfil actual no permite crear productores.")
            return
        dialog = SupplierEntryDialog(current_user=current_user, parent=parent)
        if page.dialog_runner(dialog) == QDialog.Accepted:
            refresh()
            feedback.show_success("Productor guardado.")

    def open_edit() -> None:
        supplier = selected()
        if not can_modify:
            feedback.show_warning("El perfil actual no permite modificar productores.")
            return
        if supplier is None:
            feedback.show_warning("Seleccione un productor para editar.", focus_widget=table)
            return
        dialog = SupplierEntryDialog(current_user=current_user, record_id=supplier.id, parent=parent)
        if page.dialog_runner(dialog) == QDialog.Accepted:
            refresh()
            feedback.show_success("Productor actualizado.")

    def toggle_active() -> None:
        supplier = selected()
        if not can_modify or supplier is None:
            return
        requested = not bool(supplier.active)
        message = f"¿Confirma {'reactivar' if requested else 'dar de baja'} a «{supplier.name}»?"
        if not requested:
            summary = SupplierMasterService.summary(supplier)
            if summary.documents:
                message += (
                    f"\n\nTiene {summary.documents} documentos importados. La baja no borra "
                    "nada: el productor sigue apareciendo en la cuenta corriente."
                )
        if not page.confirm(message):
            return
        SupplierMasterService(current_user).set_active(supplier, requested)
        refresh()
        feedback.show_success("Productor reactivado." if requested else "Productor dado de baja.")

    def open_detail() -> None:
        supplier = selected()
        if supplier is not None:
            page.dialog_runner(SupplierDetailDialog(supplier_id=supplier.id, parent=parent))

    def confirm(message: str) -> bool:
        answer = QMessageBox.question(
            page, "Confirmar cambio de estado", message,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    new_button.clicked.connect(open_new)
    edit_button.clicked.connect(open_edit)
    active_button.clicked.connect(toggle_active)
    table.currentCellChanged.connect(sync_actions)
    enable_master_activation(table, open_detail)

    # Puntos de extension para tests: los dialogos y confirmaciones se pueden
    # reemplazar sin abrir ventanas modales.
    page.dialog_runner = lambda dialog: dialog.exec_()
    page.confirm = confirm
    page.master_table_controller = controller
    page.refresh = refresh
    page.open_new = open_new
    page.open_edit = open_edit
    page.toggle_active = toggle_active
    page.open_detail = open_detail
    page.new_button = new_button
    page.edit_button = edit_button
    page.active_button = active_button
    page.table = table
    page.search_input = search_input
    page.empty_label = empty_label
    refresh()
    return page

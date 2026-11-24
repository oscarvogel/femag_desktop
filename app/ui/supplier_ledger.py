"""Pantalla "Cuenta corriente productores" (#941).

Muestra la posicion con cada productor (lo que la empresa le debe por tickets
de materia prima y lo que el productor le debe por pagares), el detalle de sus
documentos y sus pagos, y permite registrar y anular pagos sobre el libro de
#940. Lo excluido de la importacion queda a la vista en la misma pantalla.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.security import User
from app.models.suppliers import SupplierDocument, SupplierPayment
from app.reports.supplier_position_export import (
    export_supplier_position_pdf,
    export_supplier_position_xlsx,
)
from app.services.supplier_femagfab_sync_service import (
    FemagFabSupplierSyncService,
    SupplierSyncError,
    can_import_from_femagfab,
)
from app.services.supplier_ledger_service import (
    AllocationRequest,
    SupplierLedgerError,
    SupplierLedgerService,
    can_annul_payments,
    can_register_payments,
)
from app.services.supplier_position_service import (
    SupplierDocumentRow,
    SupplierPositionFilters,
    SupplierPositionResult,
    SupplierPositionService,
)
from app.ui.combo_autocomplete import SearchableComboBox
from app.ui.supplier_payment_dialog import METHOD_LABELS, SupplierPaymentDialog, format_money

PAYABLE_COLOR = QColor("#b91c1c")
RECEIVABLE_COLOR = QColor("#15803d")
KPI_STYLE = (
    "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
    "border-radius:8px;padding:8px 12px;"
)


class _SortableItem(QTableWidgetItem):
    """Celda que ordena por valor y muestra el texto formateado."""

    def __init__(self, text: str, value):
        super().__init__(text)
        self._value = value

    def __lt__(self, other):
        if isinstance(other, _SortableItem):
            left = self._value if self._value is not None else Decimal("-1e18")
            right = other._value if other._value is not None else Decimal("-1e18")
            return left < right
        return super().__lt__(other)


def _money_item(value: Decimal, *, colored: bool = False) -> QTableWidgetItem:
    item = _SortableItem(format_money(value), Decimal(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if colored and value != 0:
        item.setForeground(PAYABLE_COLOR if value > 0 else RECEIVABLE_COLOR)
    return item


def _date_text(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _date_item(value: date | None, *, inferred: bool = False) -> QTableWidgetItem:
    text = _date_text(value) + (" *" if inferred else "")
    item = _SortableItem(text, value.toordinal() if value else None)
    if inferred:
        item.setToolTip("Fecha inferida de los tickets vecinos: el legacy no la tenía confiable.")
    return item


def _table(headers: tuple[str, ...], object_name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName(object_name)
    table.setHorizontalHeaderLabels(headers)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class SupplierLedgerPage(QWidget):
    POSITION_HEADERS = (
        "Productor",
        "Códigos",
        "A pagar",
        "A cobrar",
        "Neto a pagar",
        "Más antiguo",
        "Días",
    )
    DOCUMENT_HEADERS = (
        "Tipo",
        "Número",
        "Fecha",
        "Importe",
        "Saldo importado",
        "Pagado en FEMAG",
        "Pendiente",
    )
    PAYMENT_HEADERS = ("Número", "Fecha", "Medio", "Referencia", "Importe", "Estado", "Registró")

    KIND_FILTERS = (
        ("Todos los documentos", None),
        ("Tickets de materia prima (a pagar)", SupplierDocument.KIND_TICKET),
        ("Pagarés (a cobrar)", SupplierDocument.KIND_PROMISSORY_NOTE),
    )

    def __init__(
        self,
        *,
        user: User | None,
        current_username: str,
        parent=None,
        service: SupplierPositionService | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("supplierLedgerPage")
        self.user = user
        self.current_username = current_username
        self.service = service or SupplierPositionService()
        self._result = SupplierPositionResult()
        self._documents: list[SupplierDocumentRow] = []
        self._all_documents: list[SupplierDocumentRow] = []
        self._payments: list[SupplierPayment] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Cuenta corriente productores")
        title.setStyleSheet("font-size:22px;font-weight:700;")
        subtitle = QLabel(
            "Lo que la empresa le debe a cada productor por tickets de materia prima, "
            "lo que el productor debe por pagarés, y los pagos registrados en FEMAG."
        )
        subtitle.setStyleSheet("color:#64748b;")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles, 1)
        self.export_excel_button = QPushButton("Exportar Excel")
        self.export_excel_button.setObjectName("supplierLedgerExportExcel")
        self.export_excel_button.clicked.connect(self.export_excel)
        self.export_pdf_button = QPushButton("Exportar PDF")
        self.export_pdf_button.setObjectName("supplierLedgerExportPdf")
        self.export_pdf_button.clicked.connect(self.export_pdf)
        self.import_button = QPushButton("Importar desde femagfab")
        self.import_button.setObjectName("supplierLedgerImportFemagfab")
        self.import_button.clicked.connect(self.import_from_femagfab)
        header.addWidget(self.import_button, 0, Qt.AlignTop)
        header.addWidget(self.export_excel_button, 0, Qt.AlignTop)
        header.addWidget(self.export_pdf_button, 0, Qt.AlignTop)
        root.addLayout(header)

        filters = QGridLayout()
        self.supplier_combo = SearchableComboBox(placeholder="Buscar productor...")
        self.supplier_combo.setObjectName("supplierLedgerSupplierCombo")
        self.supplier_combo.setMinimumWidth(280)
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("supplierLedgerKindCombo")
        for label, value in self.KIND_FILTERS:
            self.kind_combo.addItem(label, value)
        self.date_filter_check = QCheckBox("Filtrar por fecha")
        self.date_from = QDateEdit(calendarPopup=True)
        self.date_to = QDateEdit(calendarPopup=True)
        for widget in (self.date_from, self.date_to):
            widget.setDisplayFormat("dd/MM/yyyy")
            widget.setMinimumWidth(110)
            widget.setEnabled(False)
        self.date_from.setDate(QDate(QDate.currentDate().year(), 1, 1))
        self.date_to.setDate(QDate.currentDate())
        self.date_filter_check.toggled.connect(self._on_date_filter_toggled)
        self.only_balance_check = QCheckBox("Solo con saldo")
        self.only_balance_check.setChecked(True)
        consult = QPushButton("Consultar")
        consult.setObjectName("supplierLedgerConsult")
        consult.clicked.connect(self.refresh)
        clear = QPushButton("Limpiar filtros")
        clear.clicked.connect(self.clear_filters)
        for column, (label, widget) in enumerate(
            (
                ("Productor", self.supplier_combo),
                ("Documento", self.kind_combo),
                ("Desde", self.date_from),
                ("Hasta", self.date_to),
            )
        ):
            filters.addWidget(QLabel(label), 0, column)
            filters.addWidget(widget, 1, column)
        filters.addWidget(self.date_filter_check, 0, 4)
        filters.addWidget(self.only_balance_check, 1, 4)
        filters.addWidget(consult, 1, 5)
        filters.addWidget(clear, 1, 6)
        filters.setColumnStretch(0, 3)
        filters.setColumnStretch(1, 2)
        root.addLayout(filters)

        kpis = QHBoxLayout()
        self.payable_label = QLabel()
        self.receivable_label = QLabel()
        self.net_label = QLabel()
        self.suppliers_label = QLabel()
        for label in (self.payable_label, self.receivable_label, self.net_label, self.suppliers_label):
            label.setStyleSheet(KPI_STYLE)
            kpis.addWidget(label)
        kpis.addStretch(1)
        root.addLayout(kpis)

        self.exclusion_label = QLabel()
        self.exclusion_label.setObjectName("supplierLedgerExclusions")
        self.exclusion_label.setWordWrap(True)
        self.exclusion_label.setStyleSheet(
            "color:#92400e;background:#fffbeb;border:1px solid #fde68a;"
            "border-radius:6px;padding:6px 10px;"
        )
        root.addWidget(self.exclusion_label)

        splitter = QSplitter(Qt.Vertical)
        self.position_table = _table(self.POSITION_HEADERS, "supplierLedgerPositionTable")
        # Orden inicial: neto a pagar, de mayor a menor. El operador puede
        # reordenar por cualquier columna y ese orden se respeta al refrescar.
        self.position_table.horizontalHeader().setSortIndicator(4, Qt.DescendingOrder)
        self.position_table.setSortingEnabled(True)
        self.position_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.position_table.horizontalHeader().setStretchLastSection(False)
        for column, width in ((1, 110), (2, 140), (3, 140), (4, 150), (5, 100), (6, 60)):
            self.position_table.setColumnWidth(column, width)
        self.position_table.itemSelectionChanged.connect(self._on_supplier_selected)
        splitter.addWidget(self.position_table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_header = QHBoxLayout()
        self.detail_title = QLabel()
        self.detail_title.setStyleSheet("font-size:15px;font-weight:700;")
        detail_header.addWidget(self.detail_title, 1)
        self.register_button = QPushButton("Registrar pago")
        self.register_button.setObjectName("supplierLedgerRegisterPayment")
        self.register_button.setStyleSheet("font-weight:700;")
        self.register_button.clicked.connect(self.register_payment)
        self.annul_button = QPushButton("Anular pago")
        self.annul_button.setObjectName("supplierLedgerAnnulPayment")
        self.annul_button.clicked.connect(self.annul_selected_payment)
        detail_header.addWidget(self.register_button)
        detail_header.addWidget(self.annul_button)
        detail_layout.addLayout(detail_header)

        self.detail_tabs = QTabWidget()
        self.document_table = _table(self.DOCUMENT_HEADERS, "supplierLedgerDocumentTable")
        self.document_table.horizontalHeader().setSortIndicator(2, Qt.AscendingOrder)
        self.document_table.setSortingEnabled(True)
        self.payment_table = _table(self.PAYMENT_HEADERS, "supplierLedgerPaymentTable")
        self.payment_table.itemSelectionChanged.connect(self._sync_actions)
        self.detail_tabs.addTab(self.document_table, "Documentos")
        self.detail_tabs.addTab(self.payment_table, "Pagos")
        self.detail_tabs.currentChanged.connect(self._sync_actions)
        detail_layout.addWidget(self.detail_tabs, 1)
        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

    # ------------------------------------------------------------ filtros
    def _on_date_filter_toggled(self, checked: bool) -> None:
        self.date_from.setEnabled(checked)
        self.date_to.setEnabled(checked)

    def _load_supplier_combo(self) -> None:
        previous = self.supplier_combo.currentData()
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("Todos los productores", None)
        for supplier in self.service.suppliers_with_documents():
            self.supplier_combo.addItem(supplier.name, supplier.id)
        index = self.supplier_combo.findData(previous) if previous is not None else 0
        self.supplier_combo.setCurrentIndex(max(index, 0))
        self.supplier_combo.blockSignals(False)

    def current_filters(self) -> SupplierPositionFilters:
        use_dates = self.date_filter_check.isChecked()
        return SupplierPositionFilters(
            supplier_id=self.supplier_combo.currentData(),
            kind=self.kind_combo.currentData(),
            date_from=self.date_from.date().toPyDate() if use_dates else None,
            date_to=self.date_to.date().toPyDate() if use_dates else None,
            only_with_balance=self.only_balance_check.isChecked(),
        )

    def filters_label(self) -> str:
        filters = self.current_filters()
        parts = []
        if filters.supplier_id is not None:
            parts.append(f"Productor: {self.supplier_combo.currentText()}")
        if filters.kind:
            parts.append(self.kind_combo.currentText())
        if filters.date_from or filters.date_to:
            parts.append(f"Fechas {_date_text(filters.date_from)} a {_date_text(filters.date_to)}")
        if filters.only_with_balance:
            parts.append("Solo con saldo")
        return " · ".join(parts) or "Sin filtros"

    def clear_filters(self) -> None:
        self.supplier_combo.setCurrentIndex(0)
        self.kind_combo.setCurrentIndex(0)
        self.date_filter_check.setChecked(False)
        self.only_balance_check.setChecked(True)
        self.refresh()

    # ------------------------------------------------------------ datos
    def refresh(self) -> None:
        selected = self._selected_supplier_id()
        self._load_supplier_combo()
        filters = self.current_filters()
        self._all_documents = self.service.documents(filters)
        self._result = self.service.position(filters, documents=self._all_documents)
        self._render_kpis()
        self._render_position()
        self._select_supplier(selected)
        self._sync_actions()

    def _render_kpis(self) -> None:
        result = self._result
        self.payable_label.setText(f"A pagar: $ {format_money(result.payable)}")
        self.receivable_label.setText(f"A cobrar: $ {format_money(result.receivable)}")
        self.net_label.setText(f"Neto a pagar: $ {format_money(result.net)}")
        self.suppliers_label.setText(f"Productores: {len(result.rows)}")
        if result.imported_documents == 0:
            self.exclusion_label.setText(
                "No hay documentos importados de productores. Use «Importar desde "
                "femagfab» para traer el maestro y los documentos con saldo."
            )
        else:
            self.exclusion_label.setText(
                f"Excluido de la importación por falta de datos: {result.excluded_count} "
                f"documentos por $ {format_money(result.excluded_amount)}. "
                "No forman parte de estos totales."
            )

    def _render_position(self) -> None:
        table = self.position_table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._result.rows))
        today = date.today()
        for row_index, row in enumerate(self._result.rows):
            name = QTableWidgetItem(row.name)
            name.setData(Qt.UserRole, row.supplier_id)
            table.setItem(row_index, 0, name)
            table.setItem(row_index, 1, QTableWidgetItem(row.codes))
            table.setItem(row_index, 2, _money_item(row.payable))
            table.setItem(row_index, 3, _money_item(row.receivable))
            table.setItem(row_index, 4, _money_item(row.net, colored=True))
            table.setItem(row_index, 5, _date_item(row.oldest_date))
            days = row.age_days(today)
            days_item = _SortableItem("" if days is None else str(days), days)
            days_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row_index, 6, days_item)
        table.setSortingEnabled(True)

    def _selected_supplier_id(self) -> int | None:
        rows = self.position_table.selectionModel().selectedRows() if self.position_table.selectionModel() else []
        if not rows:
            return None
        item = self.position_table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _select_supplier(self, supplier_id: int | None) -> None:
        if supplier_id is None and self.current_filters().supplier_id is not None:
            supplier_id = self.current_filters().supplier_id
        target = 0 if self.position_table.rowCount() else -1
        for row in range(self.position_table.rowCount()):
            item = self.position_table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == supplier_id:
                target = row
                break
        # La seleccion se fija sin senales y el detalle se dibuja a mano: si la
        # fila ya estaba elegida, Qt no avisa y el detalle quedaria viejo.
        self.position_table.blockSignals(True)
        self.position_table.clearSelection()
        if target >= 0:
            self.position_table.selectRow(target)
        self.position_table.blockSignals(False)
        self._render_detail(self._selected_supplier_id())

    def _supplier_name(self, supplier_id: int | None) -> str:
        for row in self._result.rows:
            if row.supplier_id == supplier_id:
                return row.name
        return ""

    def _on_supplier_selected(self) -> None:
        self._render_detail(self._selected_supplier_id())

    def _render_detail(self, supplier_id: int | None) -> None:
        if supplier_id is None:
            self.detail_title.setText("Seleccione un productor para ver sus documentos y pagos.")
            self._documents = []
            self._payments = []
        else:
            self.detail_title.setText(self._supplier_name(supplier_id))
            self._documents = [row for row in self._all_documents if row.supplier_id == supplier_id]
            self._payments = self.service.payments(supplier_id)
        self._render_documents()
        self._render_payments()
        self._sync_actions()

    def _render_documents(self) -> None:
        table = self.document_table
        table.setSortingEnabled(False)
        table.setRowCount(len(self._documents))
        for row_index, document in enumerate(self._documents):
            kind = QTableWidgetItem(document.kind_label)
            kind.setData(Qt.UserRole, document.document_id)
            table.setItem(row_index, 0, kind)
            table.setItem(row_index, 1, QTableWidgetItem(document.code))
            table.setItem(row_index, 2, _date_item(document.issued_at, inferred=document.date_inferred))
            table.setItem(row_index, 3, _money_item(document.amount))
            table.setItem(row_index, 4, _money_item(document.imported_balance))
            table.setItem(row_index, 5, _money_item(document.paid))
            table.setItem(row_index, 6, _money_item(document.signed_pending, colored=True))
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _render_payments(self) -> None:
        table = self.payment_table
        table.setRowCount(len(self._payments))
        for row_index, payment in enumerate(self._payments):
            number = QTableWidgetItem(payment.number)
            number.setData(Qt.UserRole, payment.id)
            table.setItem(row_index, 0, number)
            table.setItem(row_index, 1, QTableWidgetItem(_date_text(payment.payment_date)))
            table.setItem(row_index, 2, QTableWidgetItem(METHOD_LABELS.get(payment.method, payment.method)))
            table.setItem(row_index, 3, QTableWidgetItem(payment.reference or ""))
            table.setItem(row_index, 4, _money_item(Decimal(str(payment.amount))))
            status = QTableWidgetItem("Activo" if payment.is_active else "Anulado")
            if not payment.is_active:
                status.setForeground(QColor("#94a3b8"))
                status.setToolTip(payment.annulment_reason or "")
            table.setItem(row_index, 5, status)
            table.setItem(row_index, 6, QTableWidgetItem(payment.created_by))
        table.resizeColumnsToContents()
        self.detail_tabs.setTabText(1, f"Pagos ({len(self._payments)})")

    # ------------------------------------------------------------ acciones
    def _selected_payment(self) -> SupplierPayment | None:
        rows = self.payment_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.payment_table.item(rows[0].row(), 0)
        payment_id = item.data(Qt.UserRole) if item else None
        return next((payment for payment in self._payments if payment.id == payment_id), None)

    def _pending_tickets(self) -> list[SupplierDocumentRow]:
        return [
            row
            for row in self._documents
            if row.kind == SupplierDocument.KIND_TICKET and row.pending > 0
        ]

    def _sync_actions(self, *_args) -> None:
        can_register = can_register_payments(self.user)
        has_tickets = bool(self._pending_tickets())
        self.register_button.setEnabled(can_register and has_tickets)
        if not can_register:
            self.register_button.setToolTip("No tiene permiso para registrar pagos a productores.")
        elif not has_tickets:
            self.register_button.setToolTip("El productor no tiene tickets con saldo pendiente.")
        else:
            self.register_button.setToolTip("Registrar un pago imputado a los tickets pendientes.")

        can_annul = can_annul_payments(self.user)
        payment = self._selected_payment()
        self.annul_button.setEnabled(can_annul and payment is not None and payment.is_active)
        if not can_annul:
            self.annul_button.setToolTip("No tiene permiso para anular pagos a productores.")
        else:
            self.annul_button.setToolTip("Seleccione un pago activo en la pestaña Pagos.")

        can_import = can_import_from_femagfab(self.user)
        self.import_button.setEnabled(can_import)
        self.import_button.setToolTip(
            "Trae el maestro de productores, los tickets y pagarés con saldo y abre el "
            "libro. Se puede repetir: lo ya importado no se duplica."
            if can_import
            else "Solo un usuario con permiso de importación puede traer datos de femagfab."
        )

        has_rows = bool(self._result.rows)
        self.export_excel_button.setEnabled(has_rows)
        self.export_pdf_button.setEnabled(has_rows)

    def _ledger(self) -> SupplierLedgerService:
        return SupplierLedgerService(self.current_username)

    def _make_payment_dialog(self, supplier_name: str, tickets) -> SupplierPaymentDialog:
        return SupplierPaymentDialog(supplier_name, tickets, parent=self)

    def register_payment(self) -> SupplierPayment | None:
        supplier_id = self._selected_supplier_id()
        tickets = self._pending_tickets()
        if supplier_id is None or not tickets:
            return None
        supplier = SupplierDocument.get_by_id(tickets[0].document_id).supplier
        dialog = self._make_payment_dialog(supplier.name, tickets)
        while dialog.exec_() == QDialog.Accepted:
            allocations = dialog.allocations()
            try:
                payment = self._ledger().register_payment(
                    supplier=supplier,
                    amount=dialog.total(),
                    method=dialog.method(),
                    allocations=[
                        AllocationRequest(
                            document=SupplierDocument.get_by_id(row.document_id),
                            amount=amount,
                        )
                        for row, amount in allocations
                    ],
                    payment_date=dialog.payment_date(),
                    reference=dialog.reference(),
                    observations=dialog.observations(),
                    idempotency_key=dialog.idempotency_key,
                )
            except (SupplierLedgerError, PermissionError) as exc:
                QMessageBox.warning(self, "No se pudo registrar el pago", str(exc))
                continue
            QMessageBox.information(
                self,
                "Pago registrado",
                f"Se registró el pago {payment.number} por $ {format_money(payment.amount)}.",
            )
            self.refresh()
            self.detail_tabs.setCurrentIndex(1)
            return payment
        return None

    def _ask_annulment_reason(self, payment: SupplierPayment) -> str | None:
        reason, accepted = QInputDialog.getText(
            self,
            "Anular pago",
            f"Motivo de la anulación del pago {payment.number} por $ {format_money(payment.amount)}:",
        )
        return reason if accepted else None

    def annul_selected_payment(self) -> SupplierPayment | None:
        payment = self._selected_payment()
        if payment is None or not payment.is_active:
            return None
        reason = self._ask_annulment_reason(payment)
        if reason is None:
            return None
        try:
            annulled = self._ledger().annul_payment(
                payment, authorized_by=self.user, reason=reason
            )
        except (SupplierLedgerError, PermissionError) as exc:
            QMessageBox.warning(self, "No se pudo anular el pago", str(exc))
            return None
        self.refresh()
        self.detail_tabs.setCurrentIndex(1)
        return annulled

    # ------------------------------------------------------------ importar
    def _make_sync_service(self) -> FemagFabSupplierSyncService:
        return FemagFabSupplierSyncService()

    def _confirm_import(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Importar desde femagfab",
            "Se van a traer de femagfab el maestro de productores y los tickets y "
            "pagarés con saldo, y se abrirá el libro con su saldo inicial.\n\n"
            "femagfab solo se lee. Lo que ya estaba importado no se duplica.\n\n"
            "¿Continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def import_from_femagfab(self):
        if not can_import_from_femagfab(self.user):
            QMessageBox.warning(
                self, "Importar desde femagfab", "No tiene permiso para importar productores."
            )
            return None
        if not self._confirm_import():
            return None
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            result = self._make_sync_service().run(user=self.user)
        except (SupplierSyncError, PermissionError) as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "No se pudo importar", str(exc))
            return None
        QApplication.restoreOverrideCursor()
        self.refresh()
        QMessageBox.information(
            self, "Importación terminada", "\n".join(result.summary_lines())
        )
        return result

    # ------------------------------------------------------------ exportar
    def _ask_destination(self, suffix: str, label: str) -> str | None:
        default = f"cuenta_corriente_productores_{date.today().isoformat()}.{suffix}"
        path, _ = QFileDialog.getSaveFileName(self, f"Exportar a {label}", default, f"{label} (*.{suffix})")
        if not path:
            return None
        if not path.lower().endswith(f".{suffix}"):
            path += f".{suffix}"
        return path

    def export_excel(self, path: str | None = None):
        path = path or self._ask_destination("xlsx", "Excel")
        if not path:
            return None
        return self._export(export_supplier_position_xlsx, path)

    def export_pdf(self, path: str | None = None):
        path = path or self._ask_destination("pdf", "PDF")
        if not path:
            return None
        return self._export(export_supplier_position_pdf, path)

    def _export(self, exporter, path: str):
        try:
            exported = exporter(
                self._result,
                self._all_documents,
                path,
                filters_label=self.filters_label(),
            )
        except OSError as exc:
            QMessageBox.warning(self, "No se pudo exportar", str(exc))
            return None
        QMessageBox.information(self, "Exportación lista", f"Archivo generado:\n{exported}")
        return exported

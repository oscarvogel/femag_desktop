from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.load_orders import LoadOrder, LoadOrderDestination
from app.models.masters import Client, ClientAddress, Product, product_is_loadable
from app.models.remittances import Remittance, RemittanceItem
from app.services.remittance_print_service import RemittancePrintService
from app.services.remittance_service import RemittanceService


class RemittancesPage(QWidget):
    def __init__(
        self,
        *,
        current_user: str,
        output_dir: str | Path = Path("outputs") / "remittances",
        annul_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.service = RemittanceService(current_user=current_user)
        self.current_user = current_user
        self.output_dir = Path(output_dir)
        self.annul_callback = annul_callback
        self._selected_id = None
        self.setObjectName("remittancesPage")
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        title = QLabel("Remitos")
        title.setObjectName("pageTitle")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #0f172a;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Documento independiente: carga manual o precarga opcional desde una orden de carga."))

        actions = QHBoxLayout()
        self.new_button = QPushButton("Nuevo manual")
        self.new_button.setObjectName("newRemittanceButton")
        self.from_order_button = QPushButton("Desde orden")
        self.from_order_button.setObjectName("remittanceFromOrderButton")
        self.edit_button = QPushButton("Editar borrador")
        self.edit_button.setObjectName("editRemittanceButton")
        self.issue_button = QPushButton("Emitir")
        self.issue_button.setObjectName("issueRemittanceButton")
        self.print_button = QPushButton("Imprimir PDF")
        self.print_button.setObjectName("printRemittanceButton")
        self.annul_button = QPushButton("Anular")
        self.annul_button.setObjectName("annulRemittanceButton")
        self.search_input = QLineEdit()
        self.search_input.setObjectName("remittanceSearchInput")
        self.search_input.setPlaceholderText("Buscar numero, cliente o estado...")
        self.search_input.setMinimumWidth(250)
        for button in (
            self.new_button,
            self.from_order_button,
            self.edit_button,
            self.issue_button,
            self.print_button,
            self.annul_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.search_input)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("remittancesTable")
        self.table.setHorizontalHeaderLabels(
            ["Numero", "Fecha", "Estado", "Cliente", "Entrega", "Origen", "Transporte", "Chofer"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.new_button.clicked.connect(self.open_manual_dialog)
        self.from_order_button.clicked.connect(self.open_from_order_dialog)
        self.edit_button.clicked.connect(self.edit_selected)
        self.issue_button.clicked.connect(self.issue_selected)
        self.print_button.clicked.connect(self.print_selected)
        self.annul_button.clicked.connect(self.annul_selected)
        self.search_input.textChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self._selection_changed()

    def refresh(self, *_args) -> None:
        selected = self._selected_id
        rows = self.service.list_remittances(self.search_input.text() if hasattr(self, "search_input") else None)
        self.table.setRowCount(len(rows))
        selected_row = None
        for row, remittance in enumerate(rows):
            source = f"Orden #{remittance.source_order.order_number}" if remittance.source_order else "Manual"
            values = [
                remittance.remittance_number,
                remittance.date.strftime("%d/%m/%Y"),
                remittance.status,
                remittance.client_name,
                remittance.delivery_address_text,
                source,
                remittance.carrier_name or "-",
                remittance.driver_name or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, remittance.id)
                self.table.setItem(row, column, item)
            if remittance.id == selected:
                selected_row = row
        if selected_row is not None:
            self.table.selectRow(selected_row)
        else:
            self._selected_id = None
        self._selection_changed()

    def open_manual_dialog(self) -> None:
        dialog = RemittanceEntryDialog(self.service, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self._selected_id = dialog.saved_remittance.id
            self.refresh()

    def open_from_order_dialog(self) -> None:
        chooser = RemittanceSourceDialog(parent=self)
        if chooser.exec_() != QDialog.Accepted:
            return
        order, destination = chooser.selection()
        try:
            remittance = self.service.create_from_order(order, destination)
        except Exception as exc:
            QMessageBox.warning(self, "Remito desde orden", str(exc))
            return
        self._selected_id = remittance.id
        self.refresh()
        QMessageBox.information(
            self,
            "Remito creado",
            f"Se creo {remittance.remittance_number} como borrador independiente. Puede editarlo antes de emitir.",
        )

    def edit_selected(self) -> None:
        remittance = self.selected_remittance()
        if remittance is None:
            return
        dialog = RemittanceEntryDialog(self.service, remittance=remittance, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.refresh()

    def issue_selected(self) -> None:
        remittance = self.selected_remittance()
        if remittance is None:
            return
        try:
            self.service.issue(remittance)
        except Exception as exc:
            QMessageBox.warning(self, "Emitir remito", str(exc))
            return
        self.refresh()

    def print_selected(self) -> None:
        remittance = self.selected_remittance()
        if remittance is None:
            return
        try:
            path = RemittancePrintService(current_user=self.current_user).export_pdf(remittance, self.output_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Imprimir remito", str(exc))
            return
        QMessageBox.information(self, "Remito generado", f"PDF generado en:\n{path}")

    def annul_selected(self) -> None:
        remittance = self.selected_remittance()
        if remittance is None or self.annul_callback is None:
            return
        if self.annul_callback(remittance):
            self.refresh()

    def selected_remittance(self) -> Remittance | None:
        return Remittance.get_or_none(Remittance.id == self._selected_id) if self._selected_id else None

    def _selection_changed(self) -> None:
        selected = self.table.selectedItems()
        self._selected_id = selected[0].data(Qt.UserRole) if selected else None
        remittance = self.selected_remittance()
        is_draft = bool(remittance and remittance.status == Remittance.STATUS_DRAFT)
        self.edit_button.setEnabled(is_draft)
        self.issue_button.setEnabled(is_draft)
        self.print_button.setEnabled(remittance is not None)
        self.annul_button.setEnabled(bool(remittance and remittance.status != Remittance.STATUS_ANNULLED and self.annul_callback))


class RemittanceEntryDialog(QDialog):
    def __init__(self, service: RemittanceService, *, remittance: Remittance | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.remittance = remittance
        self.saved_remittance = None
        self.setWindowTitle("Editar remito" if remittance else "Nuevo remito manual")
        self.resize(760, 560)
        self._build()
        self._load_data()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.client_combo = QComboBox()
        self.client_combo.setObjectName("remittanceClientCombo")
        self.address_combo = QComboBox()
        self.address_combo.setObjectName("remittanceAddressCombo")
        self.observations = QTextEdit()
        self.observations.setMaximumHeight(70)
        form.addRow("Fecha", self.date_input)
        form.addRow("Cliente", self.client_combo)
        form.addRow("Domicilio de entrega", self.address_combo)
        form.addRow("Observaciones", self.observations)
        layout.addLayout(form)

        row_actions = QHBoxLayout()
        add = QPushButton("Agregar producto")
        add.setObjectName("addRemittanceProductButton")
        remove = QPushButton("Quitar producto")
        row_actions.addWidget(add)
        row_actions.addWidget(remove)
        row_actions.addStretch(1)
        layout.addLayout(row_actions)
        self.items_table = QTableWidget(0, 4)
        self.items_table.setObjectName("remittanceItemsTable")
        self.items_table.setHorizontalHeaderLabels(["Producto", "Cantidad", "Unidad", "Observaciones"])
        self.items_table.setColumnWidth(0, 250)
        self.items_table.setColumnWidth(1, 120)
        self.items_table.setColumnWidth(2, 120)
        self.items_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.items_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        save = QPushButton("Guardar borrador")
        save.setObjectName("saveRemittanceButton")
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        add.clicked.connect(self.add_product_row)
        remove.clicked.connect(self.remove_product_row)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.save)
        self.client_combo.currentIndexChanged.connect(self._load_addresses)

    def _load_data(self) -> None:
        clients = Client.select().where(Client.active == True).order_by(Client.name)  # noqa: E712
        for client in clients:
            self.client_combo.addItem(client.name, client.id)
        if self.remittance:
            index = self.client_combo.findData(self.remittance.client_id)
            self.client_combo.setCurrentIndex(index)
            self._load_addresses()
            self.address_combo.setCurrentIndex(self.address_combo.findData(self.remittance.delivery_address_id))
            self.date_input.setDate(QDate(self.remittance.date.year, self.remittance.date.month, self.remittance.date.day))
            self.observations.setPlainText(self.remittance.observations or "")
            for item in self.remittance.items.order_by(RemittanceItem.id):
                self.add_product_row(item=item)
        else:
            self._load_addresses()
            self.add_product_row()

    def _load_addresses(self, *_args) -> None:
        current_id = self.address_combo.currentData()
        self.address_combo.clear()
        client_id = self.client_combo.currentData()
        if not client_id:
            return
        addresses = ClientAddress.select().where(
            ClientAddress.client == client_id,
            ClientAddress.active == True,  # noqa: E712
        ).order_by(ClientAddress.is_primary.desc(), ClientAddress.address)
        for address in addresses:
            label = f"{address.address} - {address.city}, {address.province}"
            self.address_combo.addItem(label, address.id)
        if current_id:
            self.address_combo.setCurrentIndex(self.address_combo.findData(current_id))

    def add_product_row(self, _checked=False, *, item: RemittanceItem | None = None) -> None:
        row = self.items_table.rowCount()
        self.items_table.insertRow(row)
        product_combo = QComboBox()
        products = Product.select().where(Product.active == True).order_by(Product.name)  # noqa: E712
        for product in products:
            if product_is_loadable(product):
                product_combo.addItem(product.name, product.id)
        quantity = QDoubleSpinBox()
        quantity.setRange(0.001, 999999999.999)
        quantity.setDecimals(3)
        quantity.setValue(float(item.quantity) if item else 1.0)
        unit = QLineEdit(item.unit if item else "")
        observations = QLineEdit(item.observations or "" if item else "")
        if item:
            product_combo.setCurrentIndex(product_combo.findData(item.product_id))
        product_combo.currentIndexChanged.connect(lambda _i, combo=product_combo, target=unit: self._sync_unit(combo, target))
        if not item:
            self._sync_unit(product_combo, unit)
        self.items_table.setCellWidget(row, 0, product_combo)
        self.items_table.setCellWidget(row, 1, quantity)
        self.items_table.setCellWidget(row, 2, unit)
        self.items_table.setCellWidget(row, 3, observations)

    def remove_product_row(self) -> None:
        row = self.items_table.currentRow()
        if row >= 0:
            self.items_table.removeRow(row)

    @staticmethod
    def _sync_unit(combo: QComboBox, target: QLineEdit) -> None:
        product = Product.get_or_none(Product.id == combo.currentData())
        if product:
            target.setText(product.unit)

    def save(self) -> None:
        client = Client.get_or_none(Client.id == self.client_combo.currentData())
        address = ClientAddress.get_or_none(ClientAddress.id == self.address_combo.currentData())
        products = []
        for row in range(self.items_table.rowCount()):
            combo = self.items_table.cellWidget(row, 0)
            quantity = self.items_table.cellWidget(row, 1)
            unit = self.items_table.cellWidget(row, 2)
            observations = self.items_table.cellWidget(row, 3)
            product = Product.get_or_none(Product.id == combo.currentData())
            products.append({
                "product": product,
                "quantity": quantity.value(),
                "unit": unit.text(),
                "observations": observations.text() or None,
            })
        values = {
            "client": client,
            "delivery_address": address,
            "products": products,
            "observations": self.observations.toPlainText().strip() or None,
        }
        selected_date = self.date_input.date()
        try:
            if self.remittance:
                values["date"] = selected_date.toPyDate()
                self.saved_remittance = self.service.update_draft(self.remittance, **values)
            else:
                values["remittance_date"] = selected_date.toPyDate()
                self.saved_remittance = self.service.create_manual(**values)
        except Exception as exc:
            QMessageBox.warning(self, "Guardar remito", str(exc))
            return
        self.accept()


class RemittanceSourceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear remito desde orden")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleccione un destino. Solo se copiaran sus datos y productos."))
        self.destination_combo = QComboBox()
        self.destination_combo.setObjectName("remittanceSourceDestinationCombo")
        query = (
            LoadOrderDestination.select(LoadOrderDestination, LoadOrder)
            .join(LoadOrder)
            .order_by(LoadOrder.id.desc(), LoadOrderDestination.sequence)
        )
        for destination in query:
            label = (
                f"Orden #{destination.order.order_number} - {destination.client.name} - "
                f"{destination.delivery_address.address}, {destination.delivery_address.city}"
            )
            self.destination_combo.addItem(label, (destination.order_id, destination.id))
        layout.addWidget(self.destination_combo)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        create = QPushButton("Crear borrador")
        create.setEnabled(self.destination_combo.count() > 0)
        buttons.addWidget(cancel)
        buttons.addWidget(create)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        create.clicked.connect(self.accept)

    def selection(self) -> tuple[LoadOrder, LoadOrderDestination]:
        order_id, destination_id = self.destination_combo.currentData()
        return LoadOrder.get_by_id(order_id), LoadOrderDestination.get_by_id(destination_id)

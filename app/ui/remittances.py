from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.load_orders import LoadOrder
from app.models.masters import Client, ClientAddress, Product
from app.models.remittances import Remittance
from app.services.remittance_service import RemittanceService


class RemittanceDialog(QDialog):
    def __init__(self, *, current_user: str, remittance: Remittance | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.remittance = remittance
        self.setWindowTitle("Remito")
        self.resize(820, 620)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.client_combo = QComboBox()
        self.address_combo = QComboBox()
        self.point_input = QLineEdit()
        self.point_input.setPlaceholderText("0001")
        self.number_input = QLineEdit()
        self.number_input.setPlaceholderText("00010678")
        self.reference_input = QLineEdit()
        form.addRow("Fecha", self.date_input)
        form.addRow("Cliente", self.client_combo)
        form.addRow("Domicilio", self.address_combo)
        form.addRow("Punto de venta", self.point_input)
        form.addRow("N° formulario", self.number_input)
        form.addRow("Doc. N° / referencia", self.reference_input)
        root.addLayout(form)

        self.items = QTableWidget(0, 3)
        self.items.setObjectName("remittanceItemsTable")
        self.items.setHorizontalHeaderLabels(["Producto", "Cantidad", "Descripción impresa"])
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.items, 1)

        add_row = QPushButton("+ Agregar producto")
        add_row.clicked.connect(self._add_item_row)
        root.addWidget(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.client_combo.currentIndexChanged.connect(self._refresh_addresses)
        self._load_clients()
        if self.remittance is not None:
            self._load_remittance()
        elif self.items.rowCount() == 0:
            self._add_item_row()

    def _load_clients(self) -> None:
        self.client_combo.clear()
        for client in Client.select().where(Client.active == True).order_by(Client.name):  # noqa: E712
            self.client_combo.addItem(client.name, client.id)
        self._refresh_addresses()

    def _refresh_addresses(self) -> None:
        self.address_combo.clear()
        client_id = self.client_combo.currentData()
        if not client_id:
            return
        query = (
            ClientAddress.select()
            .where((ClientAddress.client == client_id) & (ClientAddress.active == True))  # noqa: E712
            .order_by(ClientAddress.is_primary.desc(), ClientAddress.address)
        )
        for address in query:
            label = f"{address.address} - {address.city}, {address.province}"
            self.address_combo.addItem(label, address.id)

    def _add_item_row(self, product_id=None, quantity="", description="") -> None:
        row = self.items.rowCount()
        self.items.insertRow(row)
        combo = QComboBox()
        for product in Product.select().where(Product.active == True).order_by(Product.name):  # noqa: E712
            combo.addItem(product.name, product.id)
        if product_id:
            index = combo.findData(product_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.items.setCellWidget(row, 0, combo)
        self.items.setItem(row, 1, QTableWidgetItem(str(quantity)))
        self.items.setItem(row, 2, QTableWidgetItem(description))

    def _load_remittance(self) -> None:
        r = self.remittance
        index = self.client_combo.findData(r.client_id)
        if index >= 0:
            self.client_combo.setCurrentIndex(index)
        self._refresh_addresses()
        index = self.address_combo.findData(r.delivery_address_id)
        if index >= 0:
            self.address_combo.setCurrentIndex(index)
        self.date_input.setDate(QDate(r.date.year, r.date.month, r.date.day))
        self.point_input.setText(r.physical_point_of_sale or "")
        self.number_input.setText(r.physical_number or "")
        self.reference_input.setText(r.document_reference or "")
        self.items.setRowCount(0)
        for item in r.items:
            self._add_item_row(item.product_id, item.quantity, item.printed_description)
        editable = r.status == Remittance.STATUS_DRAFT
        self.client_combo.setEnabled(editable)
        self.address_combo.setEnabled(editable)
        self.items.setEnabled(editable)

    def _payload_items(self) -> list[dict]:
        payload = []
        for row in range(self.items.rowCount()):
            combo = self.items.cellWidget(row, 0)
            product_id = combo.currentData() if combo else None
            quantity_text = (self.items.item(row, 1).text() if self.items.item(row, 1) else "").strip()
            description = (self.items.item(row, 2).text() if self.items.item(row, 2) else "").strip()
            if not product_id and not quantity_text and not description:
                continue
            try:
                quantity = Decimal(quantity_text)
            except (InvalidOperation, ValueError):
                raise ValueError(f"Cantidad inválida en la fila {row + 1}.") from None
            payload.append(
                {
                    "product": Product.get_by_id(product_id),
                    "quantity": quantity,
                    "printed_description": description,
                }
            )
        return payload

    def _save(self) -> None:
        try:
            client = Client.get_by_id(self.client_combo.currentData())
            address = ClientAddress.get_by_id(self.address_combo.currentData())
            items = self._payload_items()
            date_value = self.date_input.date().toPyDate()
            service = RemittanceService(self.current_user)
            if self.remittance is None:
                self.remittance = service.create_manual(
                    client=client,
                    delivery_address=address,
                    items=items,
                    remittance_date=date_value,
                    physical_point_of_sale=self.point_input.text(),
                    physical_number=self.number_input.text(),
                    document_reference=self.reference_input.text().strip() or None,
                )
            else:
                self.remittance = service.update_draft(
                    self.remittance,
                    client=client,
                    delivery_address=address,
                    items=items,
                    date=date_value,
                    physical_point_of_sale=self.point_input.text(),
                    physical_number=self.number_input.text(),
                    document_reference=self.reference_input.text().strip() or None,
                )
        except Exception as exc:
            QMessageBox.warning(self, "Remito", str(exc))
            return
        self.accept()


class OrderDestinationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear remito desde Orden de carga")
        self.resize(620, 220)
        layout = QFormLayout(self)
        self.order_combo = QComboBox()
        self.destination_combo = QComboBox()
        self.order_combo.currentIndexChanged.connect(self._refresh_destinations)
        for order in LoadOrder.select().order_by(LoadOrder.order_number.desc()):
            self.order_combo.addItem(f"OC {order.order_number} - {order.status}", order.id)
        self._refresh_destinations()
        layout.addRow("Orden", self.order_combo)
        layout.addRow("Cliente / destino", self.destination_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _refresh_destinations(self) -> None:
        self.destination_combo.clear()
        order_id = self.order_combo.currentData()
        if not order_id:
            return
        order = LoadOrder.get_by_id(order_id)
        for destination in order.destinations.order_by(1):
            label = f"{destination.client.name} - {destination.delivery_address.address}"
            self.destination_combo.addItem(label, destination.id)

    def selection(self):
        if not self.order_combo.currentData() or not self.destination_combo.currentData():
            return None, None
        order = LoadOrder.get_by_id(self.order_combo.currentData())
        destination = order.destinations.where(order.destinations.model.id == self.destination_combo.currentData()).first()
        return order, destination


class RemittancesPage(QWidget):
    def __init__(self, *, current_user: str, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        layout = QVBoxLayout(self)
        title = QLabel("Remitos")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        actions = QHBoxLayout()
        new_button = QPushButton("+ Nuevo remito")
        new_button.setObjectName("newRemittanceButton")
        from_order = QPushButton("Crear desde Orden de carga")
        from_order.setObjectName("newRemittanceFromOrderButton")
        issue_button = QPushButton("Emitir")
        edit_button = QPushButton("Editar")
        actions.addWidget(new_button)
        actions.addWidget(from_order)
        actions.addWidget(edit_button)
        actions.addWidget(issue_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, 7)
        self.table.setObjectName("remittancesTable")
        self.table.setHorizontalHeaderLabels(
            ["Interno", "Formulario", "Fecha", "Cliente", "Destino", "Estado", "Origen"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table, 1)

        new_button.clicked.connect(self._new)
        from_order.clicked.connect(self._from_order)
        edit_button.clicked.connect(self._edit)
        issue_button.clicked.connect(self._issue)
        self.refresh()

    def refresh(self) -> None:
        rows = list(Remittance.select().order_by(Remittance.id.desc()))
        self.table.setRowCount(len(rows))
        for row, remittance in enumerate(rows):
            physical = ""
            if remittance.physical_point_of_sale and remittance.physical_number:
                physical = f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
            values = [
                remittance.remittance_number,
                physical,
                remittance.date.strftime("%d/%m/%Y"),
                remittance.client_name,
                f"{remittance.delivery_address_text} - {remittance.delivery_city or ''}",
                remittance.status,
                f"OC {remittance.source_order.order_number}" if remittance.source_order_id else "Manual",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col == 0:
                    item.setData(Qt.UserRole, remittance.id)
                self.table.setItem(row, col, item)

    def _selected(self) -> Remittance | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return Remittance.get_by_id(item.data(Qt.UserRole)) if item else None

    def _new(self) -> None:
        if RemittanceDialog(current_user=self.current_user, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _from_order(self) -> None:
        selector = OrderDestinationDialog(self)
        if selector.exec_() != QDialog.Accepted:
            return
        order, destination = selector.selection()
        if order is None or destination is None:
            return
        try:
            RemittanceService(self.current_user).create_from_order(order=order, destination=destination)
        except Exception as exc:
            QMessageBox.warning(self, "Remito", str(exc))
            return
        self.refresh()

    def _edit(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        if RemittanceDialog(current_user=self.current_user, remittance=remittance, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _issue(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        try:
            RemittanceService(self.current_user).issue(remittance)
        except Exception as exc:
            QMessageBox.warning(self, "Emitir remito", str(exc))
            return
        self.refresh()

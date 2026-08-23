from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from PyQt5.QtCore import QDate, QUrl, Qt
from PyQt5.QtGui import QDesktopServices, QDoubleValidator
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.services.remittance_print_service import RemittancePrintService
from app.services.remittance_service import RemittanceService


REMITTANCE_PRINTS_DIR = Path("outputs") / "remittances"


class RemittanceDialog(QDialog):
    def __init__(self, *, current_user: str, remittance: Remittance | None = None, parent=None):
        super().__init__(parent)
        self.current_user = current_user
        self.remittance = remittance
        self.setWindowTitle("Remito")
        self.resize(1080, 720)
        self.setMinimumSize(920, 650)
        root = QVBoxLayout(self)
        header_group = QGroupBox("Cabecera del remito")
        header_group.setObjectName("remittanceHeaderGroup")
        form = QGridLayout(header_group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.client_combo = QComboBox()
        self.address_combo = QComboBox()
        self.carrier_combo = QComboBox()
        self.carrier_combo.setObjectName("remittanceCarrierInput")
        self.truck_combo = QComboBox()
        self.truck_combo.setObjectName("remittanceTruckInput")
        self.driver_combo = QComboBox()
        self.driver_combo.setObjectName("remittanceDriverInput")
        self.point_input = QLineEdit()
        self.point_input.setPlaceholderText("0001")
        self.number_input = QLineEdit()
        self.number_input.setPlaceholderText("00010678")
        self.reference_input = QLineEdit()
        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("remittanceObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones opcionales")
        form.addWidget(QLabel("Fecha"), 0, 0)
        form.addWidget(self.date_input, 0, 1)
        form.addWidget(QLabel("Punto de venta"), 0, 2)
        form.addWidget(self.point_input, 0, 3)
        form.addWidget(QLabel("N° formulario"), 0, 4)
        form.addWidget(self.number_input, 0, 5)
        form.addWidget(QLabel("Cliente"), 1, 0)
        form.addWidget(self.client_combo, 1, 1, 1, 2)
        form.addWidget(QLabel("Domicilio"), 1, 3)
        form.addWidget(self.address_combo, 1, 4, 1, 2)
        form.addWidget(QLabel("Transportista"), 2, 0)
        form.addWidget(self.carrier_combo, 2, 1)
        form.addWidget(QLabel("Camión"), 2, 2)
        form.addWidget(self.truck_combo, 2, 3)
        form.addWidget(QLabel("Chofer"), 2, 4)
        form.addWidget(self.driver_combo, 2, 5)
        form.addWidget(QLabel("Doc. N° / referencia"), 3, 0)
        form.addWidget(self.reference_input, 3, 1, 1, 2)
        form.addWidget(QLabel("Observaciones"), 3, 3)
        form.addWidget(self.observations_input, 3, 4, 1, 2)
        for column in (1, 3, 5):
            form.setColumnStretch(column, 1)
        root.addWidget(header_group)

        detail_label = QLabel("Detalle de productos")
        detail_label.setObjectName("remittanceDetailTitle")
        root.addWidget(detail_label)

        self.items = QTableWidget(0, 3)
        self.items.setObjectName("remittanceItemsTable")
        self.items.setMinimumHeight(280)
        self.items.setHorizontalHeaderLabels(["Producto", "Cantidad", "Descripción impresa"])
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.items.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        root.addWidget(self.items, 1)

        add_row = QPushButton("+ Agregar producto")
        add_row.setObjectName("addRemittanceItemButton")
        add_row.clicked.connect(self._add_item_row)
        root.addWidget(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.client_combo.currentIndexChanged.connect(self._refresh_addresses)
        self._load_clients()
        self._load_transport()
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

    def _load_transport(self) -> None:
        for combo in (self.carrier_combo, self.truck_combo, self.driver_combo):
            combo.addItem("Sin asignar", None)
        for carrier in Carrier.select().where(Carrier.active == True).order_by(Carrier.name):  # noqa: E712
            self.carrier_combo.addItem(carrier.name, carrier.id)
        for truck in Truck.select().where(Truck.active == True).order_by(Truck.domain):  # noqa: E712
            self.truck_combo.addItem(truck.domain, truck.id)
        for driver in Driver.select().where(Driver.active == True).order_by(Driver.name):  # noqa: E712
            self.driver_combo.addItem(driver.name, driver.id)

    @staticmethod
    def _selected_model(combo: QComboBox, model):
        record_id = combo.currentData()
        return model.get_by_id(record_id) if record_id else None

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
        quantity_input = QLineEdit(str(quantity))
        quantity_input.setObjectName(f"remittanceItemQuantityInput{row}")
        quantity_input.setPlaceholderText("0,000")
        quantity_input.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        quantity_input.setValidator(QDoubleValidator(0.001, 99999999999.999, 3, quantity_input))
        description_input = QLineEdit(description)
        description_input.setObjectName(f"remittanceItemDescriptionInput{row}")
        description_input.setPlaceholderText("Descripción que se imprimirá")
        self.items.setCellWidget(row, 0, combo)
        self.items.setCellWidget(row, 1, quantity_input)
        self.items.setCellWidget(row, 2, description_input)

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
        self.observations_input.setText(r.observations or "")
        for combo, record_id in (
            (self.carrier_combo, r.carrier_id),
            (self.truck_combo, r.truck_id),
            (self.driver_combo, r.driver_id),
        ):
            index = combo.findData(record_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.items.setRowCount(0)
        for item in r.items:
            self._add_item_row(item.product_id, item.quantity, item.printed_description)
        editable = r.status == Remittance.STATUS_DRAFT
        self.client_combo.setEnabled(editable)
        self.address_combo.setEnabled(editable)
        self.date_input.setEnabled(editable)
        self.point_input.setEnabled(editable)
        self.number_input.setEnabled(editable)
        self.reference_input.setEnabled(editable)
        self.observations_input.setEnabled(editable)
        self.carrier_combo.setEnabled(editable)
        self.truck_combo.setEnabled(editable)
        self.driver_combo.setEnabled(editable)
        self.items.setEnabled(editable)

    def _payload_items(self) -> list[dict]:
        payload = []
        for row in range(self.items.rowCount()):
            combo = self.items.cellWidget(row, 0)
            product_id = combo.currentData() if combo else None
            quantity_input = self.items.cellWidget(row, 1)
            description_input = self.items.cellWidget(row, 2)
            quantity_text = (quantity_input.text() if quantity_input else "").strip()
            description = (description_input.text() if description_input else "").strip()
            if not product_id and not quantity_text and not description:
                continue
            try:
                quantity = Decimal(quantity_text.replace(",", "."))
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
            carrier = self._selected_model(self.carrier_combo, Carrier)
            truck = self._selected_model(self.truck_combo, Truck)
            driver = self._selected_model(self.driver_combo, Driver)
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
                    observations=self.observations_input.text().strip() or None,
                    carrier=carrier,
                    truck=truck,
                    driver=driver,
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
                    observations=self.observations_input.text().strip() or None,
                    carrier=carrier,
                    truck=truck,
                    driver=driver,
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
        buttons.accepted.connect(self._accept_if_valid)
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

    def _accept_if_valid(self) -> None:
        if not self.order_combo.currentData():
            QMessageBox.warning(self, "Remito", "No hay una Orden de carga seleccionada.")
            return
        if not self.destination_combo.currentData():
            QMessageBox.warning(self, "Remito", "La Orden de carga no tiene un destino seleccionable.")
            return
        self.accept()

    def selection(self):
        if not self.order_combo.currentData() or not self.destination_combo.currentData():
            return None, None
        order = LoadOrder.get_by_id(self.order_combo.currentData())
        destination_id = self.destination_combo.currentData()
        destination = order.destinations.where(order.destinations.model.id == destination_id).first()
        return order, destination


class RemittancesPage(QWidget):
    def __init__(self, *, current_user: str, parent=None, output_dir: Path | None = None):
        super().__init__(parent)
        self.current_user = current_user
        self.output_dir = output_dir or REMITTANCE_PRINTS_DIR
        layout = QVBoxLayout(self)
        title = QLabel("Remitos")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        actions = QHBoxLayout()
        new_button = QPushButton("+ Nuevo remito")
        new_button.setObjectName("newRemittanceButton")
        from_order = QPushButton("Crear desde Orden de carga")
        from_order.setObjectName("newRemittanceFromOrderButton")
        edit_button = QPushButton("Editar")
        edit_button.setObjectName("editRemittanceButton")
        issue_button = QPushButton("Emitir")
        issue_button.setObjectName("issueRemittanceButton")
        print_button = QPushButton("Imprimir formulario")
        print_button.setObjectName("printRemittanceButton")
        preview_button = QPushButton("Vista previa NO FISCAL")
        preview_button.setObjectName("previewRemittanceButton")
        annul_button = QPushButton("Anular")
        annul_button.setObjectName("annulRemittanceButton")
        calibration_button = QPushButton("Hoja de calibración")
        calibration_button.setObjectName("remittanceCalibrationButton")
        actions.addWidget(new_button)
        actions.addWidget(from_order)
        actions.addWidget(edit_button)
        actions.addWidget(issue_button)
        actions.addWidget(preview_button)
        actions.addWidget(print_button)
        actions.addWidget(annul_button)
        actions.addWidget(calibration_button)
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
        preview_button.clicked.connect(self._preview_selected)
        print_button.clicked.connect(self._print_selected)
        annul_button.clicked.connect(self._annul_selected)
        calibration_button.clicked.connect(self._print_calibration)
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
            remittance = RemittanceService(self.current_user).create_from_order(
                order=order,
                destination=destination,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito creado",
            f"Se creó {remittance.remittance_number} en borrador. Complete el número del formulario antes de emitir.",
        )

    def _edit(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        if remittance.status != Remittance.STATUS_DRAFT:
            QMessageBox.information(self, "Remitos", "Solo los remitos en borrador pueden editarse.")
            return
        if RemittanceDialog(current_user=self.current_user, remittance=remittance, parent=self).exec_() == QDialog.Accepted:
            self.refresh()

    def _issue(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        try:
            emitted = RemittanceService(self.current_user).issue(remittance)
        except Exception as exc:
            QMessageBox.warning(self, "Emitir remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito emitido",
            f"{emitted.remittance_number} quedó emitido y ya no puede editarse.",
        )

    def _print_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        physical = (
            f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
            if remittance.physical_point_of_sale and remittance.physical_number
            else remittance.remittance_number
        )
        output = self.output_dir / f"remito_{physical.replace('-', '_')}.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_preprinted(
                remittance,
                output,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Imprimir remito", str(exc))
            return
        self._open_pdf(pdf_path)

    def _preview_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        output = self.output_dir / f"vista_previa_{remittance.remittance_number.replace('-', '_')}.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_preview(
                remittance,
                output,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Vista previa de remito", str(exc))
            return
        self._open_pdf(pdf_path)

    def _annul_selected(self) -> None:
        remittance = self._selected()
        if remittance is None:
            QMessageBox.information(self, "Remitos", "Seleccione un remito.")
            return
        if remittance.status == Remittance.STATUS_ANNULLED:
            QMessageBox.information(self, "Remitos", "El remito seleccionado ya está anulado.")
            return
        reason, accepted = QInputDialog.getMultiLineText(
            self,
            "Anular remito",
            f"Motivo de anulación de {remittance.remittance_number}:",
        )
        if not accepted:
            return
        try:
            annulled = RemittanceService(self.current_user).annul(remittance, reason=reason)
        except Exception as exc:
            QMessageBox.warning(self, "Anular remito", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Remito anulado",
            f"{annulled.remittance_number} quedó anulado.",
        )

    def _print_calibration(self) -> None:
        output = self.output_dir / "calibracion_remito_preimpreso.pdf"
        try:
            pdf_path = RemittancePrintService(current_user=self.current_user).export_calibration(output)
        except Exception as exc:
            QMessageBox.warning(self, "Calibración de remito", str(exc))
            return
        self._open_pdf(pdf_path)

    @staticmethod
    def _open_pdf(path: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.information(
                None,
                "Remitos",
                f"El PDF se generó correctamente en:\n{path}",
            )

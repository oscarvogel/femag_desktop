from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.dgr import DgrLocality
from app.models.f150 import F150Batch
from app.models.masters import Client
from app.models.remittances import Remittance
from app.services.dgr_validation import (
    derive_city_province,
    is_missing_dgr_text,
)
from app.services.f150_batch_service import F150BatchService
from app.services.f150_dgr_service import (
    F150DgrCorrectionService,
    ProductDgrUpdate,
)
from app.services.f150_encoder import F150Encoder
from app.ui.dgr_locality_combo import (
    create_locality_combo,
    selected_locality_id,
)


F150_OUTPUT_DIR = Path("outputs") / "f150"


class OriginLocalityDialog(QDialog):
    """Elige la localidad DGR de la planta que sale en el F150.

    El origen va en el campo 7 de cada cabecera C y es obligatorio: sin el, la
    validacion rechaza todos los remitos.
    """

    def __init__(self, parent, localities, current, *, limit: int = 4000):
        super().__init__(parent)
        self.setWindowTitle("Configurar origen DGR")
        self._localities = list(localities)[:limit]
        self._visible: list = []
        self._chosen = None
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel("Elegi la localidad de origen de la planta (campo 7 del F150).")
        )
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por nombre o código")
        # textChanged emite el texto escrito. Conectarlo directo a _reload le
        # pasaba ese string como si fuera la localidad configurada.
        self.filter.textChanged.connect(lambda _text: self._reload())
        root.addWidget(self.filter)
        self.list = QComboBox()
        self.list.setObjectName("originLocalityCombo")
        root.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._reload(current)

    def _label(self, locality) -> str:
        country = getattr(locality, "country", None)
        country_name = country.name if country else "sin pais"
        return (
            f"{locality.name} ({locality.dgr_code_4}) - "
            f"prov. {locality.province_code_2} - {country_name}"
        )

    def _reload(self, current=None) -> None:
        self.list.clear()
        self._visible = []
        needle = self.filter.text().strip().lower() if hasattr(self, "filter") else ""
        for locality in self._localities:
            text = self._label(locality)
            if needle and needle not in text.lower():
                continue
            self._visible.append(locality)
            self.list.addItem(text, locality.id)
        # El indice del combo no es el indice de self._localities: el combo
        # tiene solo las que pasan el filtro. Preseleccionar por indice
        # apuntaria a otra localidad.
        code = getattr(current, "locality_code", None)
        if not code:
            return
        for index, locality in enumerate(self._visible):
            if locality.dgr_code_4 == code:
                self.list.setCurrentIndex(index)
                return

    def _accept(self) -> None:
        self._chosen = self.list.currentData()
        if self._chosen is None:
            QMessageBox.warning(
                self, "Origen DGR", "No hay localidades que coincidan con el filtro."
            )
            return
        self.accept()

    def selected_id(self):
        return self._chosen


class F150DgrCorrectionDialog(QDialog):
    """Corrige domicilio de entrega y rubros DGR sin entrar a MySQL (#790)."""

    def __init__(self, *, current_user: str, remittance: Remittance, parent=None):
        super().__init__(parent)
        self.setObjectName("f150DgrCorrectionDialog")
        self.setWindowTitle("Corregir datos DGR del F150")
        self.resize(760, 520)
        self.service = F150DgrCorrectionService(current_user)
        self.remittance = Remittance.get_by_id(remittance.id)
        self.address = self.remittance.delivery_address
        self.included = F150BatchService.is_included(self.remittance)
        self.result_info: dict | None = None
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        self.identity_label = QLabel()
        self.identity_label.setWordWrap(True)
        root.addWidget(self.identity_label)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_destination_tab()
        self._build_products_tab()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setObjectName("f150DgrSaveButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_destination_tab(self) -> None:
        tab = QWidget()
        form = QGridLayout(tab)
        self.address_input = QLineEdit()
        self.address_input.setObjectName("f150DgrAddressInput")
        self.city_input = QLineEdit()
        self.city_input.setObjectName("f150DgrCityInput")
        self.province_input = QLineEdit()
        self.province_input.setObjectName("f150DgrProvinceInput")
        self.locality_combo = create_locality_combo(
            object_name="f150DgrLocalityCombo",
            current_id=self.address.locality_id if self.address else None,
        )
        self.locality_combo.currentIndexChanged.connect(self._apply_locality)
        self.update_snapshot_check = QCheckBox(
            "Actualizar tambien el snapshot del remito seleccionado"
        )
        self.update_snapshot_check.setObjectName("f150DgrUpdateSnapshotCheck")
        if self.included:
            self.update_snapshot_check.setChecked(False)
            self.update_snapshot_check.setEnabled(False)
        else:
            self.update_snapshot_check.setChecked(True)
        form.addWidget(QLabel("Calle / domicilio de entrega"), 0, 0)
        form.addWidget(self.address_input, 0, 1, 1, 3)
        form.addWidget(QLabel("Localidad DGR"), 1, 0)
        form.addWidget(self.locality_combo, 1, 1, 1, 3)
        form.addWidget(QLabel("Ciudad"), 2, 0)
        form.addWidget(self.city_input, 2, 1)
        form.addWidget(QLabel("Provincia"), 2, 2)
        form.addWidget(self.province_input, 2, 3)
        form.addWidget(self.update_snapshot_check, 3, 0, 1, 4)
        note = QLabel(
            "La localidad se elige de la tabla DGR: no se inventan codigos. "
            "Si el remito ya esta en un lote F150, el TXT presentado no se toca."
        )
        note.setWordWrap(True)
        form.addWidget(note, 4, 0, 1, 4)
        self.tabs.addTab(tab, "Destino")

    def _build_products_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(
            QLabel(
                "Rubros DGR de los productos del remito. Complete los cuatro "
                "rubros y la unidad autorizada; no se usan valores por defecto."
            )
        )
        self.products_table = QTableWidget(0, 6)
        self.products_table.setObjectName("f150DgrProductsTable")
        self.products_table.setHorizontalHeaderLabels(
            ["Producto", "RH1", "RH2", "RH3", "RH4", "Unidad DGR"]
        )
        self.products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.products_table, 1)
        self.tabs.addTab(tab, "Productos")

    def _load(self) -> None:
        self.identity_label.setText(
            f"Remito {self.remittance.physical_point_of_sale}-"
            f"{self.remittance.physical_number} - {self.remittance.client_name}"
        )
        if self.address is not None:
            self.address_input.setText(self.address.address or "")
            self.city_input.setText(self.address.city or "")
            self.province_input.setText(self.address.province or "")
        self._apply_locality()
        products = self.service.products_for(self.remittance)
        self.products_table.setRowCount(len(products))
        for row, product in enumerate(products):
            name_item = QTableWidgetItem(product.name)
            name_item.setData(Qt.UserRole, product.id)
            name_item.setFlags(Qt.ItemIsEnabled)
            self.products_table.setItem(row, 0, name_item)
            for column, value in enumerate(
                (product.rh1, product.rh2, product.rh3, product.rh4, product.unidad_dgr),
                start=1,
            ):
                self.products_table.setItem(row, column, QTableWidgetItem(value or ""))

    def _apply_locality(self) -> None:
        locality_id = selected_locality_id(self.locality_combo)
        if locality_id is None:
            return
        locality = DgrLocality.get_or_none(DgrLocality.id == locality_id)
        if locality is None:
            return
        city, province = derive_city_province(locality)
        if is_missing_dgr_text(self.city_input.text()) and city:
            self.city_input.setText(city)
        if is_missing_dgr_text(self.province_input.text()) and province:
            self.province_input.setText(province)

    def _product_updates(self) -> list[ProductDgrUpdate]:
        updates = []
        for row in range(self.products_table.rowCount()):
            name_item = self.products_table.item(row, 0)
            values = [
                self.products_table.item(row, column).text().strip()
                if self.products_table.item(row, column) is not None
                else ""
                for column in range(1, 6)
            ]
            if any(not value for value in values):
                raise ValueError(
                    f"Complete RH1..RH4 y unidad DGR para {name_item.text()}."
                )
            updates.append(
                ProductDgrUpdate(
                    product_id=int(name_item.data(Qt.UserRole)),
                    rh1=values[0],
                    rh2=values[1],
                    rh3=values[2],
                    rh4=values[3],
                    unidad_dgr=values[4],
                )
            )
        return updates

    def _save(self) -> None:
        locality_id = selected_locality_id(self.locality_combo)
        if locality_id is None:
            QMessageBox.warning(
                self, "Datos DGR", "Elegi una localidad DGR de la lista."
            )
            return
        try:
            updates = self._product_updates()
            self.result_info = self.service.correct(
                self.remittance,
                address=self.address_input.text(),
                city=self.city_input.text(),
                province=self.province_input.text(),
                locality_id=locality_id,
                product_updates=updates,
                update_snapshot=self.update_snapshot_check.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "No se pudieron guardar los datos DGR", str(exc))
            return
        self.accept()


class F150Page(QWidget):
    def __init__(self, *, current_user: str, parent=None, output_dir: Path | None = None):
        super().__init__(parent)
        self.current_user = current_user
        self.output_dir = output_dir or F150_OUTPUT_DIR
        self.service = F150BatchService(current_user)
        root = QVBoxLayout(self)

        title = QLabel("Generación F150 por lote de remitos")
        title.setObjectName("f150PageTitle")
        root.addWidget(title)
        help_text = QLabel(
            "Seleccione remitos emitidos. Los incluidos en un lote anterior no pueden volver a generarse."
        )
        help_text.setWordWrap(True)
        root.addWidget(help_text)

        filters = QGroupBox("Filtros")
        grid = QGridLayout(filters)
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.client = QComboBox()
        self.number = QLineEdit()
        self.number.setPlaceholderText("Interno o número físico")
        self.status = QComboBox()
        self.status.addItem("Todos", None)
        for status in Remittance.STATUSES:
            self.status.addItem(status, status)
        self.inclusion = QComboBox()
        self.inclusion.addItem("No incluidos", False)
        self.inclusion.addItem("Todos", None)
        self.inclusion.addItem("Incluidos", True)
        apply_button = QPushButton("Aplicar filtros")
        grid.addWidget(QLabel("Desde"), 0, 0)
        grid.addWidget(self.date_from, 0, 1)
        grid.addWidget(QLabel("Hasta"), 0, 2)
        grid.addWidget(self.date_to, 0, 3)
        grid.addWidget(QLabel("Cliente"), 1, 0)
        grid.addWidget(self.client, 1, 1)
        grid.addWidget(QLabel("Número"), 1, 2)
        grid.addWidget(self.number, 1, 3)
        grid.addWidget(QLabel("Estado"), 2, 0)
        grid.addWidget(self.status, 2, 1)
        grid.addWidget(QLabel("Inclusión"), 2, 2)
        grid.addWidget(self.inclusion, 2, 3)
        grid.addWidget(apply_button, 3, 3)
        root.addWidget(filters)

        # Resumen de pendientes: al emitir se genera el F150 solo, pero si
        # falta un dato del formato el remito queda esperando. Conviene que el
        # operador lo vea de entrada, no que lo descubra por un aviso.
        self.pending_label = QLabel()
        self.pending_label.setObjectName("f150PendingLabel")
        self.pending_label.setWordWrap(True)
        #: Ultimo resumen calculado. Se guarda aparte del widget para poder
        #: verificarlo sin depender del ciclo de vida de Qt.
        self.pending_summary = ""
        root.addWidget(self.pending_label)

        actions = QHBoxLayout()
        generate = QPushButton("Generar archivo F150")
        generate.setObjectName("generateF150Button")
        actions.addWidget(generate)
        self.correct_dgr_button = QPushButton("Corregir datos DGR")
        self.correct_dgr_button.setObjectName("correctF150DgrButton")
        actions.addWidget(self.correct_dgr_button)
        self.origin_label = QLabel()
        self.origin_label.setWordWrap(True)
        actions.addWidget(self.origin_label, 1)
        self.configure_origin_button = QPushButton("Configurar origen DGR")
        self.configure_origin_button.setObjectName("configureF150OriginButton")
        actions.addWidget(self.configure_origin_button)
        root.addLayout(actions)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Generar", "Formulario", "Fecha", "Cliente", "Transportista", "Camión", "Chofer", "Estado", "Validación"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.table, 2)

        history_group = QGroupBox("Historial de lotes")
        history_layout = QVBoxLayout(history_group)
        self.history = QTableWidget(0, 6)
        self.history.setHorizontalHeaderLabels(
            ["Lote", "Fecha", "Archivo", "Remitos", "Renglones", "Usuario"]
        )
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        history_layout.addWidget(self.history)
        self.recover_button = QPushButton("Recuperar TXT del lote seleccionado")
        self.recover_button.setObjectName("recoverF150Button")
        history_layout.addWidget(self.recover_button)
        root.addWidget(history_group, 1)

        apply_button.clicked.connect(self.refresh)
        generate.clicked.connect(self._generate)
        self.correct_dgr_button.clicked.connect(self._open_dgr_correction)
        self.recover_button.clicked.connect(self._recover_txt)
        self.configure_origin_button.clicked.connect(self._configure_origin)
        self._load_clients()
        self.refresh()

    def _load_clients(self) -> None:
        self.client.clear()
        self.client.addItem("Todos", None)
        for client in Client.select().where(Client.active == True).order_by(Client.name):  # noqa: E712
            self.client.addItem(client.name, client.id)

    def refresh(self) -> None:
        self._refresh_origin()
        rows = self.service.eligible_remittances(
            date_from=self.date_from.date().toPyDate(),
            date_to=self.date_to.date().toPyDate(),
            client_id=self.client.currentData(),
            number=self.number.text(),
            status=self.status.currentData(),
            included=self.inclusion.currentData(),
        )
        self.table.setRowCount(len(rows))
        pendientes = 0
        for row_index, remittance in enumerate(rows):
            issues = self.service.validation_issues(remittance)
            if issues:
                pendientes += 1
            physical = (
                f"{remittance.physical_point_of_sale}-{remittance.physical_number}"
                if remittance.physical_point_of_sale and remittance.physical_number
                else "Sin numerar"
            )
            select_item = QTableWidgetItem()
            select_item.setData(Qt.UserRole, remittance.id)
            # El remito siempre se puede tildar: si le falta algo, el generador
            # lo rechaza nombrando el campo. Antes el checkbox quedaba
            # deshabilitado y el operador no podia avanzar sin saber por que.
            select_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            select_item.setCheckState(Qt.Unchecked)
            detail = "Listo" if not issues else "; ".join(issues)
            select_item.setToolTip(detail)
            select_item.setBackground(
                self.palette().brush(QPalette.Base) if not issues else self.palette().brush(QPalette.AlternateBase)
            )
            self.table.setItem(row_index, 0, select_item)
            values = [
                physical,
                remittance.date.strftime("%d/%m/%Y"),
                remittance.client_name,
                remittance.carrier_name or "Sin asignar",
                remittance.truck_domain or "Sin asignar",
                remittance.driver_name or "Sin asignar",
                remittance.status,
                detail,
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row_index, column, item)
        self._refresh_pending_summary(len(rows), pendientes)
        self._refresh_history()

    def _refresh_pending_summary(self, total: int, pendientes: int) -> None:
        """Pone en pantalla cuantos remitos del rango estan listos y cuantos parados."""
        self.pending_summary = F150Page._pending_summary_text(total, pendientes)
        self.pending_label.setText(self.pending_summary)
        style = "" if not pendientes else "color: #b00020; font-weight: bold;"
        if not total:
            style = ""
        self.pending_label.setStyleSheet(style)

    @staticmethod
    def _pending_summary_text(total: int, pendientes: int) -> str:
        """Al emitir el F150 sale solo, asi que lo raro es que queden pendientes.

        Los pendientes dicen que les falta en la columna Validacion. El operador
        tiene que verlo de entrada, sin recorrer fila por fila.
        """
        if not total:
            return "No hay remitos en el rango filtrado."
        listos = total - pendientes
        if not pendientes:
            return (
                f"{listos} remito{'s' if total > 1 else ''} listo"
                f"{'s' if total > 1 else ''} para el F150 en el rango filtrado."
            )
        return (
            f"{listos} listo{'s' if listos != 1 else ''} y {pendientes} pendiente"
            f"{'s' if pendientes != 1 else ''} en el rango filtrado. "
            "Los pendientes dicen qué les falta en la columna Validación: "
            "completalo y volvé a emitir el F150."
        )

    def _refresh_origin(self) -> None:
        origin = self.service.origin()
        if origin.locality_code.strip():
            self.origin_label.setText(
                f"Origen: {origin.locality_name or origin.locality_code} "
                f"({origin.locality_code})"
            )
            self.origin_label.setStyleSheet("")
            self.configure_origin_button.setVisible(False)
            return
        self.origin_label.setText(
            "Falta configurar el origen DGR de la planta. Sin origen no se puede "
            "generar ningun F150."
        )
        self.origin_label.setStyleSheet("color: #b00020; font-weight: bold;")
        self.configure_origin_button.setVisible(True)

    def _configure_origin(self) -> None:
        localities = self._localities()
        if not localities:
            QMessageBox.warning(
                self,
                "Origen DGR",
                "No hay localidades DGR cargadas. Importa las tablas de "
                "referencia DGR antes de configurar el origen.",
            )
            return
        dialog = OriginLocalityDialog(self, localities, self.service.origin())
        if dialog.exec_() != QDialog.Accepted or dialog.selected_id() is None:
            return
        try:
            self.service.set_origin_by_id(dialog.selected_id())
        except ValueError as exc:
            QMessageBox.warning(self, "Origen DGR", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self, "Origen DGR", "Origen configurado. Ya podés generar el F150."
        )

    @staticmethod
    def _localities():
        from app.models.dgr import DgrCountry, DgrLocality

        return list(
            DgrLocality.select(DgrLocality, DgrCountry).join(DgrCountry).order_by(
                DgrLocality.name
            )
        )


    def _refresh_history(self) -> None:
        batches = list(F150Batch.select().order_by(F150Batch.id.desc()))
        self.history.setRowCount(len(batches))
        for row, batch in enumerate(batches):
            values = [
                batch.batch_number,
                batch.process_date.strftime("%d/%m/%Y"),
                batch.file_name,
                batch.remittance_count,
                batch.detail_count,
                batch.created_by or "",
            ]
            for column, value in enumerate(values):
                self.history.setItem(row, column, QTableWidgetItem(str(value)))
            self.history.item(row, 0).setData(Qt.UserRole, batch.id)

    def _selected_remittances(self) -> list[Remittance]:
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                selected.append(Remittance.get_by_id(item.data(Qt.UserRole)))
        return selected

    def _generate(self) -> None:
        selected = self._selected_remittances()
        if not selected:
            QMessageBox.information(self, "F150", "Seleccione al menos un remito listo.")
            return
        suggested = self.output_dir / F150Encoder.suggested_filename(date.today())
        output_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Guardar archivo F150",
            str(suggested),
            "Archivo de texto (*.TXT *.txt)",
        )
        if not output_path:
            return
        try:
            batch = self.service.generate(selected, output_path)
        except Exception as exc:
            QMessageBox.warning(self, "F150", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "F150 generado",
            f"Se generó {batch.batch_number} con {batch.remittance_count} remito(s).",
        )

    def _selected_remittance(self) -> Remittance | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if item is None:
            return None
        return Remittance.get_by_id(item.data(Qt.UserRole))

    def _open_dgr_correction(self) -> None:
        remittance = self._selected_remittance()
        if remittance is None:
            QMessageBox.information(
                self, "Datos DGR", "Selecciona un remito de la tabla."
            )
            return
        try:
            F150DgrCorrectionService(self.current_user).require_permission()
        except PermissionError as exc:
            QMessageBox.warning(self, "Datos DGR", str(exc))
            return
        dialog = F150DgrCorrectionDialog(
            current_user=self.current_user,
            remittance=remittance,
            parent=self,
        )
        if dialog.exec_() != QDialog.Accepted or dialog.result_info is None:
            return
        info = dialog.result_info
        self.refresh()
        message = "Datos DGR guardados."
        if info.get("snapshot_updated"):
            message += " Tambien se actualizo el domicilio del remito seleccionado."
        if info.get("snapshot_skipped_reason"):
            message += "\n\n" + info["snapshot_skipped_reason"]
        remaining = info.get("remaining_issues") or []
        if remaining:
            QMessageBox.warning(
                self,
                "Datos DGR guardados con pendientes",
                message
                + "\n\nEl remito todavia tiene pendientes:\n- "
                + "\n- ".join(remaining),
            )
        else:
            QMessageBox.information(
                self,
                "Datos DGR guardados",
                message + "\n\nEl remito quedo listo para el F150.",
            )

    def _recover_txt(self) -> None:
        row = self.history.currentRow()
        item = self.history.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.information(
                self, "F150", "Selecciona un lote del historial."
            )
            return
        batch = F150Batch.get_by_id(item.data(Qt.UserRole))
        suggested = self.output_dir / batch.file_name
        output_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Recuperar archivo F150",
            str(suggested),
            "Archivo de texto (*.TXT *.txt)",
        )
        if not output_path:
            return
        try:
            output = self.service.recover_txt(batch, output_path)
        except Exception as exc:
            QMessageBox.warning(self, "No se pudo recuperar el F150", str(exc))
            return
        QMessageBox.information(
            self,
            "F150 recuperado",
            f"Archivo guardado en:\n{output}\n\n"
            "La presentacion original no fue modificada: no se creo otro lote "
            "ni se cambio su estado, fecha, usuario o numeracion.",
        )

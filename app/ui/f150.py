from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import (
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.f150 import F150Batch
from app.models.masters import Client
from app.models.remittances import Remittance
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150Encoder


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

        actions = QHBoxLayout()
        generate = QPushButton("Generar archivo F150")
        generate.setObjectName("generateF150Button")
        actions.addWidget(generate)
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
        root.addWidget(history_group, 1)

        apply_button.clicked.connect(self.refresh)
        generate.clicked.connect(self._generate)
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
        for row_index, remittance in enumerate(rows):
            issues = self.service.validation_issues(remittance)
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
        self._refresh_history()

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

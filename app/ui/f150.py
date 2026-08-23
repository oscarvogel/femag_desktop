from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDateEdit,
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
        filters.setObjectName("f150FiltersGroup")
        grid = QGridLayout(filters)
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_from.setObjectName("f150DateFromInput")
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setObjectName("f150DateToInput")
        self.client = QComboBox()
        self.client.setObjectName("f150ClientFilter")
        self.number = QLineEdit()
        self.number.setObjectName("f150NumberFilter")
        self.number.setPlaceholderText("Interno o número físico")
        self.status = QComboBox()
        self.status.setObjectName("f150StatusFilter")
        self.status.addItem("Todos", None)
        for status in Remittance.STATUSES:
            self.status.addItem(status, status)
        self.inclusion = QComboBox()
        self.inclusion.setObjectName("f150InclusionFilter")
        self.inclusion.addItem("No incluidos", False)
        self.inclusion.addItem("Todos", None)
        self.inclusion.addItem("Incluidos", True)
        apply_button = QPushButton("Aplicar filtros")
        apply_button.setObjectName("applyF150FiltersButton")
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
        actions.addStretch(1)
        root.addLayout(actions)

        self.table = QTableWidget(0, 9)
        self.table.setObjectName("f150RemittancesTable")
        self.table.setHorizontalHeaderLabels(
            ["Generar", "Formulario", "Fecha", "Cliente", "Transportista", "Camión", "Chofer", "Estado", "Validación"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 2)

        history_group = QGroupBox("Historial de lotes")
        history_layout = QVBoxLayout(history_group)
        self.history = QTableWidget(0, 6)
        self.history.setObjectName("f150HistoryTable")
        self.history.setHorizontalHeaderLabels(
            ["Lote", "Fecha", "Archivo", "Remitos", "Renglones", "Usuario"]
        )
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        history_layout.addWidget(self.history)
        root.addWidget(history_group, 1)

        apply_button.clicked.connect(self.refresh)
        generate.clicked.connect(self._generate)
        self._load_clients()
        self.refresh()

    def _load_clients(self) -> None:
        self.client.clear()
        self.client.addItem("Todos", None)
        for client in Client.select().where(Client.active == True).order_by(Client.name):  # noqa: E712
            self.client.addItem(client.name, client.id)

    def refresh(self) -> None:
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
            select_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            select_item.setCheckState(Qt.Unchecked)
            if issues:
                select_item.setFlags(Qt.ItemIsUserCheckable)
                select_item.setToolTip("; ".join(issues))
            self.table.setItem(row_index, 0, select_item)
            values = [
                physical,
                remittance.date.strftime("%d/%m/%Y"),
                remittance.client_name,
                remittance.carrier_name or "Sin asignar",
                remittance.truck_domain or "Sin asignar",
                remittance.driver_name or "Sin asignar",
                remittance.status,
                "Listo" if not issues else "; ".join(issues),
            ]
            for column, value in enumerate(values, start=1):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self._refresh_history()

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
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, batch.id)
                    item.setToolTip(batch.file_path)
                self.history.setItem(row, column, item)

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

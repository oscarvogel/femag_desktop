from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QCheckBox, QDateEdit, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout,
)

from app.models.masters import Client
from app.services.client_agenda_service import add_entry, find_entries


class ClientAgendaDialog(QDialog):
    def __init__(self, client_id, current_user, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.current_user = current_user
        client = Client.get_by_id(client_id)
        self.setWindowTitle(f"Agenda — {client.name}")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Agenda de {client.name}"))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en anotaciones")
        filters.addWidget(self.search)
        self.from_enabled = QCheckBox("Desde")
        self.date_from = QDateEdit(QDate.currentDate())
        self.to_enabled = QCheckBox("Hasta")
        self.date_to = QDateEdit(QDate.currentDate())
        for check, field in ((self.from_enabled, self.date_from), (self.to_enabled, self.date_to)):
            field.setCalendarPopup(True)
            field.setDisplayFormat("dd/MM/yyyy")
            field.setMinimumWidth(115)
            field.setEnabled(False)
            check.toggled.connect(field.setEnabled)
            filters.addWidget(check)
            filters.addWidget(field)
        search_button = QPushButton("Buscar")
        search_button.clicked.connect(self.refresh)
        self.search.returnPressed.connect(self.refresh)
        filters.addWidget(search_button)
        layout.addLayout(filters)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Fecha", "Anotación", "Registró"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel("Nueva anotación"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Fecha de lo sucedido"))
        self.entry_date = QDateEdit(QDate.currentDate())
        self.entry_date.setCalendarPopup(True)
        self.entry_date.setDisplayFormat("dd/MM/yyyy")
        self.entry_date.setMinimumWidth(115)
        row.addWidget(self.entry_date)
        row.addStretch()
        layout.addLayout(row)
        self.entry_text = QTextEdit()
        self.entry_text.setMaximumHeight(100)
        layout.addWidget(self.entry_text)
        buttons = QHBoxLayout()
        save = QPushButton("Guardar anotación")
        save.clicked.connect(self.save_entry)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        buttons.addWidget(save)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        try:
            entries = find_entries(
                self.client_id, self.search.text(),
                self.date_from.date().toPyDate() if self.from_enabled.isChecked() else None,
                self.date_to.date().toPyDate() if self.to_enabled.isChecked() else None,
            )
        except Exception as exc:
            self.status.setText(f"No se pudo consultar la agenda: {exc}")
            self.table.setRowCount(0)
            return
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for column, value in enumerate((entry.occurred_on.strftime("%d/%m/%Y"), entry.text, entry.author)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.table.resizeRowsToContents()
        self.status.setText(f"{len(entries)} anotación(es)" if entries else "No hay anotaciones que coincidan.")

    def save_entry(self):
        try:
            add_entry(self.client_id, self.entry_date.date().toPyDate(), self.entry_text.toPlainText(), self.current_user)
        except Exception as exc:
            QMessageBox.warning(self, "Agenda", f"No se pudo guardar: {exc}")
            return
        self.entry_text.clear()
        self.search.clear()
        self.from_enabled.setChecked(False)
        self.to_enabled.setChecked(False)
        self.refresh()

"""Ficha fiscal del cliente: certificados de exclusion, alicuota y observaciones (#871)."""

from __future__ import annotations

from datetime import date

from PyQt5.QtCore import QDate, Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QDoubleValidator
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.masters import Client, ClientFiscalCertificate
from app.services.client_fiscal_service import (
    ClientFiscalError,
    ClientFiscalService,
    STATUS_LABELS,
    STATUS_POR_VENCER,
    STATUS_PROGRAMADA,
    STATUS_SIN_CERTIFICADO,
    STATUS_VENCIDA,
    STATUS_VIGENTE,
)
from app.ui.form_feedback import FormFeedback

STATUS_COLORS = {
    STATUS_VIGENTE: "#166534",
    STATUS_POR_VENCER: "#92400e",
    STATUS_VENCIDA: "#991b1b",
    STATUS_PROGRAMADA: "#1e3a8a",
    STATUS_SIN_CERTIFICADO: "#6b7280",
}


def _format_datetime(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y %H:%M")
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


class ClientFiscalUploadDialog(QDialog):
    def __init__(
        self,
        *,
        kind: str,
        source_path: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.kind = kind
        label = ClientFiscalCertificate.KIND_LABELS.get(kind, kind)
        self.setObjectName("clientFiscalUploadDialog")
        self.setWindowTitle(f"Cargar certificado - {label}")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(560, 300)

        layout = QVBoxLayout(self)
        title = QLabel(f"Cargar certificado de {label}")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        form = QFormLayout()
        self.file_input = QLineEdit(source_path or "")
        self.file_input.setObjectName("clientFiscalUploadFileInput")
        self.file_input.setReadOnly(True)
        choose_button = QPushButton("Elegir PDF...")
        choose_button.setObjectName("clientFiscalUploadChooseFileButton")
        choose_button.clicked.connect(self._choose_file)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_input, 1)
        file_row.addWidget(choose_button)
        form.addRow("Archivo PDF", file_row)

        self.valid_from_input = QDateEdit(QDate.currentDate())
        self.valid_from_input.setObjectName("clientFiscalUploadFromInput")
        self.valid_from_input.setCalendarPopup(True)
        self.valid_from_input.setDisplayFormat("dd/MM/yyyy")
        form.addRow("Vigencia desde", self.valid_from_input)

        self.valid_until_input = QDateEdit(QDate.currentDate().addYears(1))
        self.valid_until_input.setObjectName("clientFiscalUploadUntilInput")
        self.valid_until_input.setCalendarPopup(True)
        self.valid_until_input.setDisplayFormat("dd/MM/yyyy")
        form.addRow("Vigencia hasta", self.valid_until_input)

        self.observations_input = QLineEdit()
        self.observations_input.setObjectName("clientFiscalUploadObservationsInput")
        self.observations_input.setPlaceholderText("Observaciones del certificado (opcional)")
        form.addRow("Observaciones", self.observations_input)
        layout.addLayout(form)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("clientFiscalUploadValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.button(QDialogButtonBox.Ok).setText("Cargar certificado")
        buttons.button(QDialogButtonBox.Ok).setObjectName("clientFiscalUploadSaveButton")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._validate_and_accept)
        layout.addWidget(buttons)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar certificado PDF", "", "PDF (*.pdf)"
        )
        if path:
            self.file_input.setText(path)

    def _validate_and_accept(self):
        if not self.file_input.text().strip():
            self.validation_label.setText("Debe elegir un archivo PDF.")
            return
        if self.valid_until_input.date() < self.valid_from_input.date():
            self.validation_label.setText(
                "La vigencia hasta no puede ser anterior a la vigencia desde."
            )
            return
        self.validation_label.clear()
        self.accept()

    def source_path(self) -> str:
        return self.file_input.text().strip()

    def valid_from(self) -> date:
        return self.valid_from_input.date().toPyDate()

    def valid_until(self) -> date:
        return self.valid_until_input.date().toPyDate()

    def observations(self) -> str:
        return self.observations_input.text().strip()


class ClientFiscalDialog(QDialog):
    def __init__(
        self,
        *,
        current_user: str,
        client_id: int,
        service: ClientFiscalService | None = None,
        can_edit: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("clientFiscalDialog")
        self.current_user = current_user
        self.service = service or ClientFiscalService(current_user=current_user)
        self.client = Client.get_by_id(client_id)
        self.can_edit = can_edit
        self.setWindowTitle(f"Datos fiscales - {self.client.name}")
        self.setModal(True)
        self.resize(860, 620)
        self.setMinimumSize(720, 520)

        layout = QVBoxLayout(self)
        title = QLabel(f"Datos fiscales - {self.client.name}")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        status_row = QHBoxLayout()
        self.status_groups = {}
        for kind in ClientFiscalCertificate.KINDS:
            group, status_label, view_button, upload_button = self._build_status_group(kind)
            self.status_groups[kind] = {
                "label": status_label,
                "view": view_button,
                "upload": upload_button,
            }
            status_row.addWidget(group, 1)
        layout.addLayout(status_row)

        fiscal_group = QGroupBox("Alicuota y observaciones")
        fiscal_layout = QFormLayout(fiscal_group)
        self.alicuota_input = QLineEdit()
        self.alicuota_input.setObjectName("clientFiscalRentasAlicuotaInput")
        self.alicuota_input.setPlaceholderText("Sin definir")
        validator = QDoubleValidator(0.0, 100.0, 2, self.alicuota_input)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.alicuota_input.setValidator(validator)
        fiscal_layout.addRow("Alicuota de Rentas (%)", self.alicuota_input)
        self.observations_input = QTextEdit()
        self.observations_input.setObjectName("clientFiscalObservationsInput")
        self.observations_input.setPlaceholderText(
            "Observaciones fiscales del cliente"
        )
        self.observations_input.setFixedHeight(70)
        fiscal_layout.addRow("Observaciones", self.observations_input)
        self.save_fiscal_button = QPushButton("Guardar datos fiscales")
        self.save_fiscal_button.setObjectName("clientFiscalSaveDataButton")
        self.save_fiscal_button.clicked.connect(self._save_fiscal_data)
        self.save_fiscal_button.setEnabled(self.can_edit)
        fiscal_layout.addRow("", self.save_fiscal_button)
        layout.addWidget(fiscal_group)

        history_label = QLabel("Historial de certificados")
        history_label.setProperty("uiRole", "sectionTitle")
        layout.addWidget(history_label)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setObjectName("clientFiscalHistoryTable")
        self.history_table.setHorizontalHeaderLabels(
            ["Tipo", "Desde", "Hasta", "Estado", "Cargado", "Usuario", "Archivo"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.cellDoubleClicked.connect(self._open_history_row)
        layout.addWidget(self.history_table, 1)

        self.feedback = FormFeedback("clientFiscalFeedback")
        layout.addWidget(self.feedback)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("clientFiscalCloseButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.refresh()

    def _build_status_group(self, kind: str):
        label = ClientFiscalCertificate.KIND_LABELS.get(kind, kind)
        group = QGroupBox(label)
        group_layout = QVBoxLayout(group)
        status_label = QLabel("-")
        status_label.setObjectName(f"clientFiscal{kind.title()}StatusLabel")
        status_label.setWordWrap(True)
        group_layout.addWidget(status_label)
        buttons = QHBoxLayout()
        view_button = QPushButton("Ver PDF")
        view_button.setObjectName(f"clientFiscalView{kind.title()}Button")
        view_button.clicked.connect(lambda _checked=False, k=kind: self._view_current(k))
        upload_button = QPushButton("Cargar / Reemplazar")
        upload_button.setObjectName(f"clientFiscalUpload{kind.title()}Button")
        upload_button.clicked.connect(lambda _checked=False, k=kind: self._upload(k))
        upload_button.setEnabled(self.can_edit)
        buttons.addWidget(view_button)
        buttons.addWidget(upload_button)
        buttons.addStretch(1)
        group_layout.addLayout(buttons)
        return group, status_label, view_button, upload_button

    def refresh(self) -> None:
        today = date.today()
        for kind in ClientFiscalCertificate.KINDS:
            state = self.service.certificate_state(self.client, kind, today=today)
            widgets = self.status_groups[kind]
            text = state["status_label"]
            if state["certificate"] is not None:
                text += (
                    f" · vence {state['valid_until']:%d/%m/%Y}"
                    f" ({state['days_left']} dias)"
                )
            else:
                text += " · cargue el certificado para habilitar el control"
            widgets["label"].setText(text)
            widgets["label"].setStyleSheet(
                f"font-weight: 700; color: {STATUS_COLORS.get(state['status'], '#374151')};"
            )
            widgets["view"].setEnabled(state["certificate"] is not None)
        self.alicuota_input.setText(
            "" if self.client.rentas_alicuota is None else str(self.client.rentas_alicuota)
        )
        self.observations_input.setPlainText(self.client.fiscal_observations or "")
        self._render_history()

    def _render_history(self) -> None:
        rows = self.service.certificates(self.client)
        self.history_table.setRowCount(len(rows))
        today = date.today()
        for index, certificate in enumerate(rows):
            status = self.service.status_for_dates(
                certificate.valid_from, certificate.valid_until, today=today
            )
            values = (
                ClientFiscalCertificate.KIND_LABELS.get(
                    certificate.kind, certificate.kind
                ),
                certificate.valid_from.strftime("%d/%m/%Y"),
                certificate.valid_until.strftime("%d/%m/%Y"),
                STATUS_LABELS.get(status, status),
                _format_datetime(certificate.uploaded_at),
                certificate.uploaded_by or "",
                certificate.original_name,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, certificate.id)
                self.history_table.setItem(index, column, item)

    def _selected_history_certificate(self):
        row = self.history_table.currentRow()
        if row < 0:
            return None
        item = self.history_table.item(row, 0)
        if item is None:
            return None
        certificate_id = item.data(Qt.UserRole)
        if certificate_id is None:
            return None
        return ClientFiscalCertificate.get_or_none(
            ClientFiscalCertificate.id == certificate_id
        )

    def _open_history_row(self, row: int, _column: int) -> None:
        self.history_table.selectRow(row)
        certificate = self._selected_history_certificate()
        if certificate is not None:
            self._open_certificate(certificate)

    def _view_current(self, kind: str) -> None:
        certificate = self.service.current_certificate(self.client, kind)
        if certificate is not None:
            self._open_certificate(certificate)

    def _open_certificate(self, certificate: ClientFiscalCertificate) -> None:
        path = self.service.absolute_path(certificate)
        if not path.exists():
            self.feedback.show_error(
                f"No se encontro el archivo del certificado: {path}"
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _upload(self, kind: str) -> None:
        dialog = ClientFiscalUploadDialog(kind=kind, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            self.service.upload_certificate(
                client=self.client,
                kind=kind,
                source_path=dialog.source_path(),
                valid_from=dialog.valid_from(),
                valid_until=dialog.valid_until(),
                observations=dialog.observations(),
            )
        except ClientFiscalError as exc:
            self.feedback.show_error(str(exc))
            return
        self.client = Client.get_by_id(self.client.id)
        self.refresh()
        self.feedback.show_success("Certificado cargado correctamente.")

    def _save_fiscal_data(self) -> None:
        try:
            self.client = self.service.update_fiscal_data(
                self.client,
                rentas_alicuota=self.alicuota_input.text().strip() or None,
                fiscal_observations=self.observations_input.toPlainText(),
            )
        except ClientFiscalError as exc:
            self.feedback.show_error(str(exc))
            return
        self.refresh()
        self.feedback.show_success("Datos fiscales actualizados.")


__all__ = ["ClientFiscalDialog", "ClientFiscalUploadDialog"]

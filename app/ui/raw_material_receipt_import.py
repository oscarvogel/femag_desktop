from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt5.QtCore import QDate, QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QDateEdit, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.raw_material_receipt_import_service import (
    RawMaterialReceiptImportService, ReceiptPreview, ReceiptTotals,
)
from app.ui.form_feedback import FormFeedback


STATUS_LABELS = {
    RawMaterialReceiptImportService.NEW: "Nuevo",
    RawMaterialReceiptImportService.UNCHANGED: "Sin cambios",
    RawMaterialReceiptImportService.MODIFIED: "Modificado",
}

PHASE_LABELS = {
    "consulta": "Consultando femagfab",
    "revision": "Revisando tickets",
    "importacion": "Importando tickets",
}


def _kg(value: Decimal) -> str:
    return f"{value:,.2f}"


def _range_text(start: date, end: date) -> str:
    if start == end:
        return f"el {start:%d/%m/%Y}"
    return f"entre el {start:%d/%m/%Y} y el {end:%d/%m/%Y}"


class _WorkerSignals(QObject):
    progress = pyqtSignal(str, int, int)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


class _PreviewWorker(QRunnable):
    """Consulta el rango fuera del hilo de UI para no congelar la pantalla."""

    def __init__(self, service, start: date, end: date):
        super().__init__()
        self.service = service
        self.start = start
        self.end = end
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.service.preview_range(
                self.start, self.end, progress=self.signals.progress.emit
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


class _ImportWorker(QRunnable):
    """Importa los tickets pendientes informando avance ticket por ticket."""

    def __init__(self, service, previews):
        super().__init__()
        self.service = service
        self.previews = previews
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            created = self.service.import_new(
                self.previews, progress=self.signals.progress.emit
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(created)
        finally:
            self.signals.finished.emit()


class RawMaterialReceiptImportPage(QWidget):
    """Consulta tickets de materia prima en femagfab e importa los faltantes.

    La pantalla nunca escribe en femagfab. La fécula teórica se calcula siempre
    como TOTALK * PROMEDIO / 100; el valor FECULA del legacy se muestra
    sólo como referencia histórica.
    """

    HEADERS = (
        "Ticket",
        "Proveedor",
        "Producto",
        "Kg liquidables",
        "Rinde promedio",
        "Fécula teórica",
        "Fécula legacy",
        "Estado",
    )

    def __init__(self, parent=None, *, service: RawMaterialReceiptImportService | None = None):
        super().__init__(parent)
        self.service = service or RawMaterialReceiptImportService()
        self.previews = []
        self.totals: ReceiptTotals | None = None
        self._last_start: date | None = None
        self._last_end: date | None = None
        self._worker = None
        self._busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        heading = QLabel("Recepciones de materia prima")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subheading = QLabel(
            "Consulta los tickets finalizados de femagfab por rango de fechas. "
            "La importación guarda un snapshot propio y no modifica el sistema de balanza."
        )
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        layout.addWidget(subheading)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Desde"))
        self.start_day = QDateEdit(self._first_of_month())
        self.start_day.setObjectName("rawMaterialReceiptFromInput")
        self.start_day.setCalendarPopup(True)
        self.start_day.setDisplayFormat("dd/MM/yyyy")
        controls.addWidget(self.start_day)
        controls.addWidget(QLabel("Hasta"))
        self.end_day = QDateEdit(QDate.currentDate())
        self.end_day.setObjectName("rawMaterialReceiptToInput")
        self.end_day.setCalendarPopup(True)
        self.end_day.setDisplayFormat("dd/MM/yyyy")
        controls.addWidget(self.end_day)
        self.consult_button = QPushButton("Consultar")
        self.consult_button.setObjectName("rawMaterialReceiptConsultButton")
        self.consult_button.setProperty("uiRole", "primary")
        self.consult_button.clicked.connect(self.refresh)
        controls.addWidget(self.consult_button)
        self.import_button = QPushButton("Importar nuevos")
        self.import_button.setObjectName("rawMaterialReceiptImportButton")
        self.import_button.setProperty("uiRole", "secondary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.import_new)
        controls.addWidget(self.import_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setObjectName("rawMaterialReceiptProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Listo")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.summary_label = QLabel("Seleccione un rango de fechas y consulte los tickets.")
        self.summary_label.setObjectName("rawMaterialReceiptSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "font-weight:700;background:#f8fafc;border:1px solid #e2e8f0;"
            "border-radius:8px;padding:8px 12px;"
        )
        layout.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setObjectName("rawMaterialReceiptTable")
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.feedback = FormFeedback("rawMaterialReceiptFeedback")
        self.feedback.show_info("Seleccione un rango de fechas y consulte los tickets.")
        layout.addWidget(self.feedback)

    @staticmethod
    def _first_of_month() -> QDate:
        today = QDate.currentDate()
        return QDate(today.year(), today.month(), 1)

    @staticmethod
    def _to_date(qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())

    def selected_start_date(self) -> date:
        return self._to_date(self.start_day.date())

    def selected_end_date(self) -> date:
        return self._to_date(self.end_day.date())

    def _clear_result(self, message: str) -> None:
        """Deja la pantalla sin filas previas que puedan importarse por error."""
        self.previews = []
        self.totals = None
        self.table.setRowCount(0)
        self.import_button.setEnabled(False)
        self.summary_label.setText(message)

    def _render_rows(self) -> None:
        self.table.setRowCount(len(self.previews))
        for index, preview in enumerate(self.previews):
            row = preview.row
            values = [
                row.comp,
                row.supplier_name or row.supplier_code,
                row.product_name or row.product_code,
                _kg(row.payable_kg),
                f"{row.yield_average:,.2f} %",
                _kg(row.theoretical_starch_kg),
                _kg(row.legacy_starch_kg),
                STATUS_LABELS.get(preview.status, preview.status),
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))

    def _render_totals(self, totals: ReceiptTotals, pending: int) -> None:
        self.summary_label.setText(
            f"{totals.tickets} ticket(s) · {_kg(totals.payable_kg)} kg liquidables · "
            f"rinde ponderado {totals.weighted_yield:,.2f} % · "
            f"{_kg(totals.theoretical_starch_kg)} kg de fécula teórica · "
            f"{pending} ticket(s) sin importar"
        )

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.consult_button.setEnabled(not busy)
        if busy:
            self.import_button.setEnabled(False)
            self.progress.setVisible(True)
            self.progress.setRange(0, 0)
            self.progress.setFormat(message)
        else:
            self._worker = None
            self.progress.setVisible(False)
            self.import_button.setEnabled(
                any(preview.status == self.service.NEW for preview in self.previews)
            )

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        label = PHASE_LABELS.get(phase, "Procesando")
        if total <= 0:
            self.progress.setRange(0, 0)
            self.progress.setFormat(f"{label}…")
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        percent = int(done * 100 / total)
        self.progress.setFormat(f"{label} {done}/{total} ({percent} %)")

    def _on_preview_failed(self, message: str) -> None:
        self._clear_result("No se pudo consultar femagfab.")
        self.feedback.show_error(f"No se pudo consultar femagfab: {message}")

    def _on_preview_done(self, result) -> None:
        self.previews, self.totals = result
        self._render_rows()
        pending = sum(1 for preview in self.previews if preview.status == self.service.NEW)
        self._render_totals(self.totals, pending)
        self.import_button.setEnabled(pending > 0)
        if pending:
            self.feedback.show_info(
                f"{pending} ticket(s) nuevos {_range_text(self._last_start, self._last_end)}."
            )
        else:
            self.feedback.show_success(
                f"Sin tickets nuevos {_range_text(self._last_start, self._last_end)}."
            )

    def _on_import_failed(self, message: str) -> None:
        self.feedback.show_error(f"No se pudo importar: {message}")

    def _on_import_done(self, created: int) -> None:
        self.previews = [
            ReceiptPreview(
                row=preview.row,
                source_key=preview.source_key,
                status=(
                    self.service.UNCHANGED
                    if preview.status == self.service.NEW
                    else preview.status
                ),
            )
            for preview in self.previews
        ]
        self._render_rows()
        if self.totals is not None:
            self._render_totals(self.totals, 0)
        self.feedback.show_success(f"Se importaron {created} ticket(s) nuevos.")

    def _start_worker(self, worker) -> None:
        worker.signals.progress.connect(self._on_progress)
        worker.signals.failed.connect(
            self._on_preview_failed
            if isinstance(worker, _PreviewWorker)
            else self._on_import_failed
        )
        worker.signals.succeeded.connect(
            self._on_preview_done
            if isinstance(worker, _PreviewWorker)
            else self._on_import_done
        )
        worker.signals.finished.connect(self._finish)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _finish(self) -> None:
        self._set_busy(False)

    def refresh(self) -> None:
        if self._busy:
            return
        start = self.selected_start_date()
        end = self.selected_end_date()
        if start > end:
            self.feedback.show_error("La fecha desde no puede ser posterior a la fecha hasta.")
            return
        self._last_start = start
        self._last_end = end
        self._clear_result(f"Consultando tickets {_range_text(start, end)}…")
        self._set_busy(True, "Consultando femagfab…")
        self.feedback.show_info(f"Consultando tickets {_range_text(start, end)}…")
        self._start_worker(_PreviewWorker(self.service, start, end))

    def import_new(self) -> None:
        if self._busy:
            return
        pending = [preview for preview in self.previews if preview.status == self.service.NEW]
        if not pending:
            self.feedback.show_info("No hay tickets nuevos para importar.")
            return
        self._set_busy(True, "Importando tickets…")
        self._start_worker(_ImportWorker(self.service, pending))

"""Dialogo para corregir lote y fechas por contenido de una orden (#864)."""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path

from PyQt5.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.services.load_order_traceability_service import (
    LINE,
    LOOSE_CONTENT,
    PALLET_CONTENT,
    LoadOrderTraceabilityError,
    LoadOrderTraceabilityService,
)
from app.services.order_capture_ai_service import (
    CaptureError,
    CaptureLineContext,
    CaptureProposal,
    extract_capture,
    load_capture_config,
)

logger = logging.getLogger("femag.ui.captura_ia")

NO_DATE = QDate(1900, 1, 1)

#: Los editores de la tabla usan fondo claro; el texto tiene que ser oscuro
#: para que se lea tambien en el tema oscuro. Sin esto, el color de texto del
#: tema claro/oscuro se hereda y queda casi invisible sobre el fondo claro.
_EDITOR_STYLE = (
    "background-color: #ffffff; color: #1f2937; "
    "border: 1px solid #cbd9e8; border-radius: 6px; padding: 2px 6px;"
)
_EDITOR_PREFILLED_STYLE = (
    "background-color: #eaf7ef; color: #1f2937; "
    "border: 1px solid #9fd3b4; border-radius: 6px; padding: 2px 6px;"
)


def _line_index(order: LoadOrder):
    lines = list(
        LoadOrderProduct.select()
        .where(LoadOrderProduct.order == order)
        .order_by(LoadOrderProduct.id)
    )
    by_key: dict[tuple[int, int], LoadOrderProduct] = {}
    by_product: dict[int, LoadOrderProduct] = {}
    for line in lines:
        if line.destination_id is None:
            by_product.setdefault(line.product_id, line)
        else:
            by_key.setdefault((line.destination_id, line.product_id), line)
    return lines, by_key, by_product


def _line_for(allocation, by_key, by_product) -> LoadOrderProduct | None:
    return by_key.get(
        (allocation.destination_id, allocation.product_id)
    ) or by_product.get(allocation.product_id)


def _destination_label(destination) -> str:
    if destination is None:
        return ""
    address = destination.delivery_address
    if address is None:
        return ""
    return " - ".join(
        part for part in (address.address, address.city) if part
    )


def load_order_traceability_rows(order: LoadOrder) -> list[dict]:
    order = LoadOrder.get_by_id(order.id)
    rows: list[dict] = []
    _lines, by_key, by_product = _line_index(order)

    pallet_allocations = list(
        LoadOrderPalletAllocation.select()
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence, LoadOrderPalletAllocation.id)
    )
    for allocation in pallet_allocations:
        line = _line_for(allocation, by_key, by_product)
        rows.append(
            _row(
                kind=PALLET_CONTENT,
                item_id=allocation.id,
                content=f"Pallet {allocation.pallet.sequence}",
                destination=allocation.destination,
                product=allocation.product,
                quantity=allocation.quantity,
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
                line_id=line.id if line is not None else None,
            )
        )

    loose_allocations = list(
        LoadOrderLooseAllocation.select()
        .where(LoadOrderLooseAllocation.order == order)
        .order_by(LoadOrderLooseAllocation.id)
    )
    for allocation in loose_allocations:
        line = _line_for(allocation, by_key, by_product)
        rows.append(
            _row(
                kind=LOOSE_CONTENT,
                item_id=allocation.id,
                content="Suelto",
                destination=allocation.destination,
                product=allocation.product,
                quantity=allocation.quantity,
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
                line_id=line.id if line is not None else None,
            )
        )

    if rows:
        return rows

    # Orden legacy sin composicion: se edita directamente el renglon.
    for line in _lines:
        rows.append(
            _row(
                kind=LINE,
                item_id=line.id,
                content="Renglon",
                destination=line.destination,
                product=line.product,
                quantity=line.quantity,
                lote=line.lote,
                fecha_elaboracion=line.fecha_elaboracion,
                fecha_envasado=line.fecha_envasado,
                line_id=line.id,
            )
        )
    return rows


def _row(
    *,
    kind: str,
    item_id: int,
    content: str,
    destination,
    product,
    quantity,
    lote,
    fecha_elaboracion,
    fecha_envasado,
    line_id: int | None = None,
) -> dict:
    client_name = ""
    if destination is not None:
        client_name = destination.client.name
    return {
        "kind": kind,
        "id": item_id,
        "line_id": line_id,
        "content": content,
        "client": client_name,
        "destination": _destination_label(destination),
        "product": product.name if product is not None else "",
        "quantity": quantity,
        "lote": lote,
        "fecha_elaboracion": fecha_elaboracion,
        "fecha_envasado": fecha_envasado,
    }


def capture_line_contexts(order: LoadOrder) -> list[CaptureLineContext]:
    """Arma las lineas que se le pasan a la IA desde la orden local."""

    order = LoadOrder.get_by_id(order.id)
    lines, by_key, by_product = _line_index(order)
    pallets: dict[int, int] = {}
    loose: set[int] = set()

    for allocation in (
        LoadOrderPalletAllocation.select()
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
    ):
        line = _line_for(allocation, by_key, by_product)
        if line is not None:
            pallets[line.id] = pallets.get(line.id, 0) + 1
    for allocation in LoadOrderLooseAllocation.select().where(
        LoadOrderLooseAllocation.order == order
    ):
        line = _line_for(allocation, by_key, by_product)
        if line is not None:
            loose.add(line.id)

    contexts: list[CaptureLineContext] = []
    fallback_client = order.client.name if order.client else ""
    for line in lines:
        destination = line.destination
        client = (
            destination.client.name if destination is not None else fallback_client
        )
        contexts.append(
            CaptureLineContext(
                key=f"n{line.id}",
                product=line.product.name,
                client=client,
                destination=_destination_label(destination),
                quantity=float(line.quantity or 0),
                unit=line.unit or (line.product.unit or ""),
                pallets=pallets.get(line.id, 0),
                loose=line.id in loose,
            )
        )
    return contexts


def _row_sort_key(row: dict):
    if row["kind"] == PALLET_CONTENT:
        match = re.search(r"\d+", row.get("content") or "")
        return (0, int(match.group()) if match else 0)
    if row["kind"] == LOOSE_CONTENT:
        return (1, 0)
    return (2, int(row.get("id") or 0))


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def capture_updates_for_rows(
    rows: list[dict], proposal: CaptureProposal
) -> tuple[list[dict], list[str], int]:
    """Traduce la propuesta de IA a valores para las filas del dialogo.

    La IA viene por linea de despacho (producto + cliente + destino); el
    dialogo muestra una fila por contenido. Se reparten los lotes por la
    cantidad de pallets cuando el modelo la informa y, si no, se aplica el
    primer lote con una advertencia. No escribe en la base.
    """

    rows_by_line: dict[int, list[dict]] = {}
    for row in rows:
        if row.get("line_id") is not None:
            rows_by_line.setdefault(int(row["line_id"]), []).append(row)

    updates: dict[tuple[str, int], dict] = {}
    warnings: list[str] = list(proposal.warnings)

    for proposal_line in proposal.lines:
        warnings.extend(proposal_line.warnings)
        if proposal_line.match_status != "matched" or not proposal_line.line_key:
            continue
        if not proposal_line.line_key.startswith("n"):
            continue
        try:
            line_id = int(proposal_line.line_key[1:])
        except (TypeError, ValueError):
            continue
        line_rows = sorted(rows_by_line.get(line_id, []), key=_row_sort_key)
        lots = [
            lot
            for lot in proposal_line.lots
            if lot.lote or lot.fecha_elaboracion or lot.fecha_envasado
        ]
        if not line_rows or not lots:
            continue

        assignments: list[tuple[list[dict], object]] = []
        if len(lots) == 1:
            assignments.append((line_rows, lots[0]))
        else:
            counts = [lot.pallets for lot in lots]
            if (
                all(count is not None and count > 0 for count in counts)
                and sum(counts) == len(line_rows)
            ):
                cursor = 0
                for lot, count in zip(lots, counts):
                    amount = int(count or 0)
                    assignments.append(
                        (line_rows[cursor : cursor + amount], lot)
                    )
                    cursor += amount
            else:
                assignments.append((line_rows, lots[0]))
                warnings.append(
                    f"{proposal_line.product_text}: se detectaron {len(lots)} "
                    "lotes pero no se pudo repartir los pallets; se cargo el primero."
                )

        for target_rows, lot in assignments:
            for row in target_rows:
                key = (row["kind"], int(row["id"]))
                updates[key] = {
                    "kind": row["kind"],
                    "id": int(row["id"]),
                    "lote": lot.lote or row.get("lote") or "",
                    "fecha_elaboracion": (
                        lot.fecha_elaboracion
                        or row.get("fecha_elaboracion")
                    ),
                    "fecha_envasado": (
                        lot.fecha_envasado or row.get("fecha_envasado")
                    ),
                }

    return list(updates.values()), _dedupe(warnings), len(updates)


class _CaptureSignals(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()


class _CaptureTask(QRunnable):
    """Lee la foto/PDF fuera del hilo de la UI."""

    def __init__(
        self,
        *,
        data: bytes,
        filename: str,
        mime: str,
        contexts: list[CaptureLineContext],
        order_number: int,
        order_date,
        client_name: str | None,
        config,
    ):
        super().__init__()
        self.signals = _CaptureSignals()
        self.data = data
        self.filename = filename
        self.mime = mime
        self.contexts = contexts
        self.order_number = order_number
        self.order_date = order_date
        self.client_name = client_name
        self.config = config

    def run(self) -> None:
        try:
            proposal = extract_capture(
                self.data,
                self.filename,
                self.mime,
                load_lines=self.contexts,
                order_number=self.order_number,
                order_date=self.order_date,
                client_name=self.client_name,
                config=self.config,
            )
        except CaptureError as exc:
            self.signals.failed.emit(str(exc))
        except Exception:
            logger.exception("Fallo inesperado en la precarga con IA del escritorio")
            self.signals.failed.emit(
                "No se pudo leer la orden con IA. Proba de nuevo o carga los datos a mano."
            )
        else:
            self.signals.completed.emit(proposal)
        finally:
            self.signals.finished.emit()


class LoadOrderTraceabilityDialog(QDialog):
    def __init__(
        self,
        service: LoadOrderTraceabilityService,
        order: LoadOrder,
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.order = LoadOrder.get_by_id(order.id)
        self.updated_count = 0
        self.setObjectName("loadOrderTraceabilityDialog")
        self.setWindowTitle(
            f"Lote / fecha OC-{self.order.order_number:06d}"
        )
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setMinimumSize(900, 520)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(max(1000, int(available.width() * 0.9)), available.width() - 40)
            height = min(max(560, int(available.height() * 0.8)), available.height() - 40)
        else:
            width, height = 1200, 640
        self.resize(width, height)

        layout = QVBoxLayout(self)

        title = QLabel(f"Lote / fecha - OC-{self.order.order_number:06d}")
        title.setObjectName("loadOrderTraceabilityTitle")
        title.setProperty("uiRole", "sectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Corrija el lote y las fechas de cada contenido. El cliente, el "
            "destino, el producto y la cantidad no se modifican."
        )
        hint.setWordWrap(True)
        hint.setProperty("uiRole", "muted")
        top_row = QHBoxLayout()
        top_row.addWidget(hint, 1)
        self.import_button = QPushButton("Importar foto/PDF")
        self.import_button.setObjectName("loadOrderTraceabilityAiButton")
        self.import_button.setToolTip(
            "Lee el lote y las fechas desde una foto o PDF y precarga la tabla."
        )
        self.import_button.clicked.connect(self._import_capture)
        top_row.addWidget(self.import_button)
        layout.addLayout(top_row)

        self.capture_status = QLabel("")
        self.capture_status.setObjectName("loadOrderTraceabilityCaptureStatus")
        self.capture_status.setProperty("uiRole", "muted")
        self.capture_status.setWordWrap(True)
        layout.addWidget(self.capture_status)
        self._capture_task = None
        self._capture_busy = False
        self._capture_used = False

        self.table = QTableWidget(0, 8)
        self.table.setObjectName("loadOrderTraceabilityTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Contenido",
                "Cliente",
                "Destino",
                "Producto",
                "Cant.",
                "Lote",
                "Elaboracion",
                "Envasado",
            ]
        )
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(5, 190)
        # Las fechas necesitan ancho para mostrar dd/MM/yyyy completo y no
        # quedar cortadas por el boton del calendario.
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        self.table.setColumnWidth(6, 125)
        self.table.setColumnWidth(7, 115)
        header.setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        layout.addWidget(self.table, 1)

        self.reason_input = None
        if self.order.status == LoadOrder.STATUS_CLOSED:
            reason_label = QLabel("Motivo del cambio (obligatorio en orden cerrada)")
            reason_label.setProperty("uiRole", "muted")
            layout.addWidget(reason_label)
            self.reason_input = QTextEdit()
            self.reason_input.setObjectName("loadOrderTraceabilityReasonInput")
            self.reason_input.setPlaceholderText(
                "Indique por que se corrige el lote o las fechas."
            )
            self.reason_input.setFixedHeight(70)
            layout.addWidget(self.reason_input)

        self.validation_label = QLabel("")
        self.validation_label.setObjectName("loadOrderTraceabilityValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b42318;")
        layout.addWidget(self.validation_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.setText("Cancelar")
        self.cancel_button.setObjectName("loadOrderTraceabilityCancelButton")
        self.save_button = buttons.button(QDialogButtonBox.Ok)
        self.save_button.setText("Guardar cambios")
        self.save_button.setObjectName("loadOrderTraceabilitySaveButton")
        layout.addWidget(buttons)

        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)

        self._populate()

    def _populate(self) -> None:
        self._rows = load_order_traceability_rows(self.order)
        self.table.setRowCount(len(self._rows))
        self._editors: list[dict] = []
        for index, row in enumerate(self._rows):
            self.table.setItem(index, 0, QTableWidgetItem(row["content"]))
            self.table.setItem(index, 1, QTableWidgetItem(row["client"]))
            self.table.setItem(index, 2, QTableWidgetItem(row["destination"]))
            self.table.setItem(index, 3, QTableWidgetItem(row["product"]))
            self.table.setItem(index, 4, QTableWidgetItem(f"{float(row['quantity']):g}"))

            lote_edit = QLineEdit(row["lote"] or "")
            lote_edit.setObjectName(f"loadOrderTraceabilityLote_{index}")
            lote_edit.setStyleSheet(_EDITOR_STYLE)
            self.table.setCellWidget(index, 5, lote_edit)

            elab_edit = self._date_edit(row["fecha_elaboracion"])
            elab_edit.setObjectName(f"loadOrderTraceabilityElab_{index}")
            self.table.setCellWidget(index, 6, elab_edit)

            envasado_edit = self._date_edit(row["fecha_envasado"])
            envasado_edit.setObjectName(f"loadOrderTraceabilityEnvasado_{index}")
            self.table.setCellWidget(index, 7, envasado_edit)

            self._editors.append(
                {
                    "row": row,
                    "lote": lote_edit,
                    "elaboracion": elab_edit,
                    "envasado": envasado_edit,
                }
            )

        self._editors_by_key = {
            (row["kind"], int(row["id"])): editor
            for row, editor in zip(self._rows, self._editors)
        }

    @staticmethod
    def _date_edit(value) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd/MM/yyyy")
        edit.setMinimumDate(NO_DATE)
        edit.setSpecialValueText("-")
        edit.setStyleSheet(_EDITOR_STYLE)
        if value is None:
            edit.setDate(NO_DATE)
        else:
            edit.setDate(QDate(value.year, value.month, value.day))
        return edit

    @staticmethod
    def _date_value(edit: QDateEdit):
        value = edit.date()
        if value == NO_DATE:
            return None
        return value.toPyDate()

    # ------------------------------------------------------------------
    # Precarga con IA (#913)
    # ------------------------------------------------------------------

    def _import_capture(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Importar orden desde foto o PDF",
            "",
            "Imagenes y PDF (*.jpg *.jpeg *.png *.webp *.gif *.pdf)",
        )
        if not path:
            return

        config = load_capture_config()
        if not config.enabled:
            QMessageBox.warning(
                self,
                "Importar con IA",
                config.disabled_reason()
                or "La importacion con IA no esta configurada.",
            )
            return

        file_path = Path(path)
        try:
            size = file_path.stat().st_size
        except OSError as exc:
            QMessageBox.warning(
                self, "Importar con IA", f"No se pudo leer el archivo: {exc}"
            )
            return
        if size > max(1, config.max_mb) * 1024 * 1024:
            QMessageBox.warning(
                self,
                "Importar con IA",
                f"El archivo supera el maximo de {config.max_mb} MB.",
            )
            return
        try:
            data = file_path.read_bytes()
        except OSError as exc:
            QMessageBox.warning(
                self, "Importar con IA", f"No se pudo leer el archivo: {exc}"
            )
            return

        contexts = capture_line_contexts(self.order)
        if not contexts:
            QMessageBox.warning(
                self,
                "Importar con IA",
                "La orden no tiene lineas para precargar.",
            )
            return

        mime = mimetypes.guess_type(file_path.name)[0] or ""
        self._set_capture_busy(True, "Leyendo la orden con IA...")
        task = _CaptureTask(
            data=data,
            filename=file_path.name,
            mime=mime,
            contexts=contexts,
            order_number=self.order.order_number,
            order_date=self.order.date,
            client_name=self.order.client.name if self.order.client else None,
            config=config,
        )
        task.signals.completed.connect(self._capture_completed)
        task.signals.failed.connect(self._capture_failed)
        task.signals.finished.connect(self._capture_finished)
        self._capture_task = task
        QThreadPool.globalInstance().start(task)

    def _set_capture_busy(self, busy: bool, message: str = "") -> None:
        if busy == self._capture_busy:
            if message:
                self.capture_status.setText(message)
            return
        self._capture_busy = busy
        self.import_button.setEnabled(not busy)
        self.save_button.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()
        if message:
            self.capture_status.setText(message)

    def _capture_completed(self, proposal) -> None:
        updates, warnings, applied = capture_updates_for_rows(
            self._rows, proposal
        )
        self._apply_capture_updates(updates)
        if applied:
            self._capture_used = True
            message = (
                f"Se precargaron {applied} fila(s). Revisa lote y fechas "
                "antes de guardar los cambios."
            )
            self.capture_status.setText(message)
        else:
            message = (
                "La IA no pudo precargar ninguna fila. Revisa la imagen o "
                "carga los datos a mano."
            )
            self.capture_status.setText(message)
        if warnings:
            QMessageBox.information(
                self,
                "Precarga con IA",
                message + "\n\n" + "\n".join(warnings[:12]),
            )

    def _capture_failed(self, message: str) -> None:
        self.capture_status.setText("No se pudo leer la orden con IA.")
        QMessageBox.warning(self, "Importar con IA", message)

    def _capture_finished(self) -> None:
        self._capture_task = None
        self._set_capture_busy(False)

    def _apply_capture_updates(self, updates: list[dict]) -> None:
        for update in updates:
            editor = self._editors_by_key.get(
                (update["kind"], int(update["id"]))
            )
            if editor is None:
                continue
            editor["lote"].setText(update["lote"] or "")
            elab = update.get("fecha_elaboracion")
            editor["elaboracion"].setDate(
                QDate(elab.year, elab.month, elab.day) if elab else NO_DATE
            )
            envasado = update.get("fecha_envasado")
            editor["envasado"].setDate(
                QDate(envasado.year, envasado.month, envasado.day)
                if envasado
                else NO_DATE
            )
            for widget in (
                editor["lote"],
                editor["elaboracion"],
                editor["envasado"],
            ):
                widget.setStyleSheet(_EDITOR_PREFILLED_STYLE)

    def done(self, result: int) -> None:
        if self._capture_busy:
            self._set_capture_busy(False)
        super().done(result)

    def reason(self) -> str:
        if self.reason_input is None:
            return ""
        return self.reason_input.toPlainText().strip()

    def items(self) -> list[dict]:
        return [
            {
                "kind": editor["row"]["kind"],
                "id": editor["row"]["id"],
                "lote": editor["lote"].text().strip(),
                "fecha_elaboracion": self._date_value(editor["elaboracion"]),
                "fecha_envasado": self._date_value(editor["envasado"]),
            }
            for editor in self._editors
        ]

    def _save(self) -> None:
        self.validation_label.clear()
        if self.reason_input is not None and not self.reason():
            self.validation_label.setText(
                "Debe indicar el motivo del cambio en una orden cerrada."
            )
            self.reason_input.setFocus()
            return
        try:
            self.updated_count = self.service.update_lote_fecha(
                self.order,
                self.items(),
                reason=self.reason(),
                source=(
                    "Precarga asistida por IA" if self._capture_used else None
                ),
            )
        except (LoadOrderTraceabilityError, ValueError) as exc:
            self.validation_label.setText(str(exc))
            return
        self.accept()


__all__ = [
    "LoadOrderTraceabilityDialog",
    "load_order_traceability_rows",
]

"""Envio automatico de presupuestos al emitir una orden (#706).

La emision de la orden tiene que responder ya: el build del PDF, el gateway de
WhatsApp y el SMTP pueden tardar. Por eso el envio corre en un ``QRunnable``
sobre el ``QThreadPool``, igual que la campana de lista de precios (#763), y la
pantalla solo muestra el resumen cuando termina.

Este modulo es la parte de interfaz: la regla y la trazabilidad viven en
``app.services.budget_auto_send_service``.
"""

from __future__ import annotations

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

#: Los workers viven hasta que terminan: si se libera el ``QRunnable`` antes de
#: que Qt entregue la senal, el resumen no se muestra.
_ACTIVE_WORKERS: list["BudgetAutoSendWorker"] = []


class BudgetAutoSendSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class BudgetAutoSendWorker(QRunnable):
    """Corre el envio de los presupuestos de una orden emitida."""

    def __init__(self, service, order):
        super().__init__()
        self.service = service
        self.order = order
        self.signals = BudgetAutoSendSignals()
        self.setAutoDelete(False)

    def run(self) -> None:  # pragma: no cover - corre en otro hilo
        try:
            resultado = self.service.dispatch_order(self.order)
        except Exception as exc:  # noqa: BLE001 - el resumen informa el error
            self.signals.error.emit(str(exc))
            return
        self.signals.finished.emit(resultado)


def start_budget_auto_send(
    issued,
    *,
    current_user: str,
    prints_dir,
    parent=None,
) -> bool:
    """Lanza el envio automatico si el puesto lo tiene habilitado (#706).

    Devuelve ``True`` si se encolo el envio. Con el flag apagado no toca nada:
    emitir una orden se comporta exactamente como antes.
    """
    from app.services.budget_auto_send_service import (
        BudgetAutoSendService,
        autoenvio_habilitado,
    )

    if not autoenvio_habilitado():
        return False

    worker = BudgetAutoSendWorker(
        BudgetAutoSendService(current_user, prints_dir=prints_dir),
        issued,
    )
    _ACTIVE_WORKERS.append(worker)

    def _release(*_args) -> None:
        if worker in _ACTIVE_WORKERS:
            _ACTIVE_WORKERS.remove(worker)

    worker.signals.finished.connect(_release)
    worker.signals.error.connect(_release)
    worker.signals.finished.connect(
        lambda resultado: _show_result(resultado, parent=parent)
    )
    worker.signals.error.connect(
        lambda message: QMessageBox.warning(
            parent,
            "Envio automatico de presupuestos",
            f"No se pudo completar el envio automatico: {message}",
        )
    )
    QThreadPool.globalInstance().start(worker)
    return True


def _show_result(resultado, *, parent=None) -> None:
    """Muestra el resumen del envio, con el motivo de lo que no salio."""

    enviados = resultado.enviados
    omitidos = resultado.omitidos
    fallidos = resultado.fallidos
    faltantes = omitidos + fallidos

    if not faltantes:
        QMessageBox.information(
            parent,
            "Envio automatico de presupuestos",
            f"Se enviaron {len(enviados)} presupuesto(s) de la orden "
            f"OC-{resultado.order_number:06d}.",
        )
        return

    lineas = [
        f"Presupuestos de la orden OC-{resultado.order_number:06d}:",
        f"Enviados: {len(enviados)} · Omitidos: {len(omitidos)} · Fallidos: {len(fallidos)}",
    ]
    for item in faltantes:
        detalle = f" - {item.cliente} ({item.canal})"
        if item.motivo:
            detalle += f": {item.motivo}"
        lineas.append(detalle)
    box = QMessageBox(QMessageBox.Warning, "Envio automatico de presupuestos", "\n".join(lineas), parent=parent)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.show()

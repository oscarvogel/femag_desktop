from __future__ import annotations

import logging
import os
import subprocess

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt5.QtWidgets import QMessageBox

from app.build_info import APP_ID, BUILD_VERSION
from app.services.update_service import UpdateInfo, download_installer, fetch_update_info


logger = logging.getLogger("femag.updater")


class _Signals(QObject):
    update_found = pyqtSignal(object)
    downloaded = pyqtSignal(str)
    failed = pyqtSignal(str)


class _CheckWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            info = fetch_update_info(BUILD_VERSION)
        except Exception:
            logger.exception("No se pudo consultar el manifest de actualizacion")
            return
        if info is not None:
            self.signals.update_found.emit(info)


class _DownloadWorker(QRunnable):
    def __init__(self, info: UpdateInfo):
        super().__init__()
        self.info = info
        self.signals = _Signals()

    def run(self) -> None:
        try:
            path = download_installer(self.info)
        except Exception as exc:
            logger.exception("No se pudo descargar/validar la actualizacion")
            self.signals.failed.emit(str(exc))
            return
        self.signals.downloaded.emit(str(path))


def _show_update_dialog(window, info: UpdateInfo) -> None:
    notes = info.notes or "Hay una nueva versión disponible."
    message = (
        f"Versión instalada: {BUILD_VERSION}\n"
        f"Nueva versión: {info.version}\n\n"
        f"{notes}\n\n"
        "¿Desea descargar el instalador ahora?"
    )
    buttons = QMessageBox.Yes | QMessageBox.No
    answer = QMessageBox.question(window, "Nueva versión de FEMAG", message, buttons, QMessageBox.Yes)
    if answer != QMessageBox.Yes:
        return

    worker = _DownloadWorker(info)
    worker.signals.failed.connect(
        lambda text: QMessageBox.warning(window, "Actualización FEMAG", f"No se pudo descargar la actualización:\n{text}")
    )

    def _launch(path: str) -> None:
        answer2 = QMessageBox.question(
            window,
            "Actualización descargada",
            "El instalador fue descargado y validado correctamente.\n\n"
            "¿Desea cerrar FEMAG e instalar la nueva versión ahora?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer2 != QMessageBox.Yes:
            return
        try:
            subprocess.Popen([path], close_fds=True)
        except OSError as exc:
            logger.exception("No se pudo ejecutar el instalador descargado")
            QMessageBox.warning(window, "Actualización FEMAG", f"No se pudo abrir el instalador:\n{exc}")
            return
        logger.info("Instalador de FEMAG %s lanzado; cerrando aplicacion", info.version)
        window.close()

    worker.signals.downloaded.connect(_launch)
    window._femag_update_download_worker = worker
    QThreadPool.globalInstance().start(worker)


def install_update_extension() -> None:
    if os.getenv("FEMAG_DISABLE_UPDATE_CHECK") == "1":
        return
    if APP_ID != "femag":
        return

    from app.ui.desktop_app import FemagDesktopWindow

    if getattr(FemagDesktopWindow, "_vogel_update_extension_installed", False):
        return

    original_init = FemagDesktopWindow.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if kwargs.get("demo_mode"):
            return
        worker = _CheckWorker()
        worker.signals.update_found.connect(lambda info: _show_update_dialog(self, info))
        self._femag_update_check_worker = worker
        QTimer.singleShot(1500, lambda: QThreadPool.globalInstance().start(worker))

    FemagDesktopWindow.__init__ = patched_init
    FemagDesktopWindow._vogel_update_extension_installed = True

from __future__ import annotations

import logging
import os
import subprocess
import webbrowser

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton

from app.build_info import APP_ID, BUILD_VERSION
from app.services.production_health import run_production_health_check
from app.services.update_service import (
    CANDIDATE_CHANNEL,
    UpdateInfo,
    candidate_receipt_matches,
    download_installer,
    fetch_update_info,
    get_update_channel,
)


logger = logging.getLogger("femag.updater")
PROMOTION_WORKFLOW_URL = (
    "https://github.com/oscarvogel/femag_desktop/actions/workflows/promote-production.yml"
)


class _Signals(QObject):
    update_found = pyqtSignal(object)
    downloaded = pyqtSignal(str)
    pilot_ready = pyqtSignal(object)
    failed = pyqtSignal(str)


class _CheckWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _Signals()

    def run(self) -> None:
        try:
            info = fetch_update_info(BUILD_VERSION, channel=get_update_channel())
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


class _PilotApprovalWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _Signals()

    def run(self) -> None:
        health = run_production_health_check()
        if not health.ok:
            self.signals.failed.emit(
                "El health-check local no paso.\n"
                f"Validaciones completadas: {', '.join(health.checks) or 'ninguna'}\n"
                f"Error: {health.error}"
            )
            return
        try:
            # Se usa una version sentinel valida para leer la identidad exacta del
            # candidate aunque ya sea la version instalada en la PC piloto.
            info = fetch_update_info(
                "0000.00.00.00.00.00",
                channel=CANDIDATE_CHANNEL,
            )
        except Exception as exc:
            logger.exception("No se pudo consultar candidate para aprobacion")
            self.signals.failed.emit(f"No se pudo consultar candidate: {exc}")
            return
        if info is None:
            self.signals.failed.emit("El manifest candidate no es valido o no esta disponible.")
            return
        if info.version != BUILD_VERSION:
            self.signals.failed.emit(
                "La version instalada no coincide con candidate.\n"
                f"Instalada: {BUILD_VERSION}\nCandidate: {info.version}"
            )
            return
        if not candidate_receipt_matches(version=info.version, sha256=info.sha256):
            self.signals.failed.emit(
                "Esta instalacion no tiene el recibo SHA256 del candidate validado. "
                "Instale candidate desde el updater de esta PC piloto antes de aprobar."
            )
            return
        self.signals.pilot_ready.emit(info)


def _show_update_dialog(window, info: UpdateInfo) -> None:
    notes = info.notes or "Hay una nueva versión disponible."
    channel_note = "\nCanal piloto: candidate." if info.channel == CANDIDATE_CHANNEL else ""
    message = (
        f"Versión instalada: {BUILD_VERSION}\n"
        f"Nueva versión: {info.version}\n"
        f"{channel_note}\n\n"
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


def _start_pilot_approval(window) -> None:
    worker = _PilotApprovalWorker()
    worker.signals.failed.connect(
        lambda text: QMessageBox.warning(window, "Aprobación de candidate", text)
    )

    def _ready(info: UpdateInfo) -> None:
        confirmation = QMessageBox.question(
            window,
            "Aprobar candidate para producción",
            "La PC piloto pasó el health-check y coincide exactamente con candidate.\n\n"
            f"Versión: {info.version}\n"
            f"SHA256: {info.sha256}\n\n"
            "La promoción se autoriza en GitHub con su sesión de administrador; "
            "FEMAG no almacena tokens ni credenciales de GitHub.\n\n"
            "¿Abrir ahora la aprobación segura?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(f"version={info.version}\nsha256={info.sha256}")
        if not webbrowser.open(PROMOTION_WORKFLOW_URL):
            QMessageBox.warning(
                window,
                "Aprobación de candidate",
                "No se pudo abrir el navegador. Abra GitHub Actions y ejecute "
                "manualmente el workflow Promote FEMAG production.",
            )
            return
        QMessageBox.information(
            window,
            "Aprobación de candidate",
            "Se abrió GitHub Actions y se copiaron versión y SHA256 al portapapeles. "
            "El workflow volverá a verificar ambos valores antes de promover exactamente ese build.",
        )

    worker.signals.pilot_ready.connect(_ready)
    window._femag_pilot_approval_worker = worker
    QThreadPool.globalInstance().start(worker)


def install_update_extension() -> None:
    if os.getenv("FEMAG_DISABLE_UPDATE_CHECK") == "1":
        return
    if APP_ID != "femag":
        return

    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    if getattr(FemagDesktopWindow, "_vogel_update_extension_installed", False):
        return

    original_init = FemagDesktopWindow.__init__
    original_topbar = FemagDesktopWindow._topbar

    def patched_topbar(self):
        bar = original_topbar(self)
        if get_update_channel() != CANDIDATE_CHANNEL:
            return bar
        if not PermissionService.is_administrator(self.user):
            return bar
        button = QPushButton("Aprobar esta versión para producción")
        button.setObjectName("approveCandidateButton")
        button.setToolTip("Disponible sólo en la PC piloto configurada para el canal candidate.")
        button.clicked.connect(lambda: _start_pilot_approval(self))
        layout = bar.layout()
        if layout is not None:
            layout.insertWidget(max(0, layout.count() - 2), button)
        return bar

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if kwargs.get("demo_mode"):
            return
        worker = _CheckWorker()
        worker.signals.update_found.connect(lambda info: _show_update_dialog(self, info))
        self._femag_update_check_worker = worker
        QTimer.singleShot(1500, lambda: QThreadPool.globalInstance().start(worker))

    FemagDesktopWindow._topbar = patched_topbar
    FemagDesktopWindow.__init__ = patched_init
    FemagDesktopWindow._vogel_update_extension_installed = True

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from app.services.permission_service import PermissionService
from app.ui.collection_due_report import CollectionDueReportDialog

_INSTALLED = False
_ORIGINAL_NAVIGATE = None


def install_collection_due_report_extension() -> None:
    global _INSTALLED, _ORIGINAL_NAVIGATE
    if _INSTALLED:
        return
    from app.ui.desktop_app import FemagDesktopWindow

    _ORIGINAL_NAVIGATE = FemagDesktopWindow._navigate

    def _navigate_with_report(self, row: int) -> None:
        item = self.nav.item(row)
        route = item.data(Qt.UserRole) if item else None
        if route != "collection_due_report":
            _ORIGINAL_NAVIGATE(self, row)
            return
        user = self.user
        if (
            user is None
            or not user.active
            or not PermissionService().has_permission(user, "Inicio", "ver", "Pendientes")
        ):
            QMessageBox.warning(
                self,
                "Vencimientos de cobranzas",
                "El usuario actual no tiene permiso para ver este informe.",
            )
            return
        CollectionDueReportDialog(self).exec_()

    FemagDesktopWindow._navigate = _navigate_with_report
    _INSTALLED = True


def uninstall_collection_due_report_extension() -> None:
    global _INSTALLED, _ORIGINAL_NAVIGATE
    if not _INSTALLED:
        return
    from app.ui.desktop_app import FemagDesktopWindow

    if _ORIGINAL_NAVIGATE is not None:
        FemagDesktopWindow._navigate = _ORIGINAL_NAVIGATE
    _ORIGINAL_NAVIGATE = None
    _INSTALLED = False

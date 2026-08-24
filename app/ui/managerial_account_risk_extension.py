from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from app.services.permission_service import PermissionService
from app.ui.managerial_account_risk import ManagerialAccountRiskDialog


_INSTALLED = False
_ORIGINAL_NAVIGATE = None


def install_managerial_account_risk_extension() -> None:
    global _INSTALLED, _ORIGINAL_NAVIGATE
    if _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow

    _ORIGINAL_NAVIGATE = FemagDesktopWindow._navigate

    def _navigate_with_report(self, row: int) -> None:
        item = self.nav.item(row)
        route = item.data(Qt.UserRole) if item else None
        if route != "managerial_account_risk":
            _ORIGINAL_NAVIGATE(self, row)
            return
        if not PermissionService().can_view_managerial_dashboard(self.user):
            QMessageBox.warning(
                self,
                "Cuenta corriente y deuda vencida",
                "El usuario actual no tiene permiso gerencial para ver este informe.",
            )
            return
        ManagerialAccountRiskDialog(self).exec_()

    FemagDesktopWindow._navigate = _navigate_with_report
    _INSTALLED = True


def uninstall_managerial_account_risk_extension() -> None:
    global _INSTALLED, _ORIGINAL_NAVIGATE
    if not _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow

    if _ORIGINAL_NAVIGATE is not None:
        FemagDesktopWindow._navigate = _ORIGINAL_NAVIGATE
    _ORIGINAL_NAVIGATE = None
    _INSTALLED = False

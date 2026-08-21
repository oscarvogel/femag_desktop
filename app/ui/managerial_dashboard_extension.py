from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport
from app.services.permission_service import PermissionService


_INSTALLED = False


def install_managerial_dashboard_extension() -> None:
    """Open the managerial dashboard as local HTML in the system browser.

    The sidebar and permission model remain native FEMAG concerns. The report
    itself is generated from the same Python reporting service and rendered by
    the workstation browser, avoiding an embedded Chromium dependency.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow

    original_navigate = FemagDesktopWindow._navigate

    def _navigate_with_managerial_dashboard(self, row: int) -> None:
        item = self.nav.item(row)
        route = item.data(Qt.UserRole) if item else None
        if route != "managerial_dashboard":
            original_navigate(self, row)
            return
        if not PermissionService().can_view_managerial_dashboard(self.user):
            QMessageBox.warning(
                self,
                "Dashboard Gerencial",
                "El usuario actual no tiene permiso para ver el Dashboard Gerencial.",
            )
            return
        try:
            ManagerialDashboardHtmlReport().open()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Dashboard Gerencial",
                f"No se pudo generar el dashboard gerencial:\n{exc}",
            )

    FemagDesktopWindow._navigate = _navigate_with_managerial_dashboard
    _INSTALLED = True

from __future__ import annotations

from app.services.permission_service import PermissionService
from app.ui.managerial_dashboard import ManagerialDashboardPage


_INSTALLED = False


def install_managerial_dashboard_extension() -> None:
    """Attach the managerial dashboard page to the desktop shell once.

    The main desktop window is intentionally kept stable because it is a very
    large integration module. This extension registers the real page after the
    normal shell build while preserving the sidebar route and permission model.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow

    original_build = FemagDesktopWindow._build

    def _build_with_managerial_dashboard(self) -> None:
        original_build(self)
        if not PermissionService().can_view_managerial_dashboard(self.user):
            return
        if "managerial_dashboard" in self._route_indexes:
            return
        self._add_page(
            "managerial_dashboard",
            ManagerialDashboardPage(parent=self),
        )

    FemagDesktopWindow._build = _build_with_managerial_dashboard
    _INSTALLED = True

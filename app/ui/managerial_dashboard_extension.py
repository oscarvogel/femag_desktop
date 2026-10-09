from __future__ import annotations

from app.services.menu_service import set_managerial_dashboard_menu_enabled


_INSTALLED = False
_ORIGINAL_ADD_MASTER_PAGES = None


def install_managerial_dashboard_extension() -> None:
    """Register the managerial dashboard as an internal FEMAG page."""
    global _INSTALLED, _ORIGINAL_ADD_MASTER_PAGES
    if _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.managerial_dashboard import ManagerialDashboardPage

    set_managerial_dashboard_menu_enabled(True)
    _ORIGINAL_ADD_MASTER_PAGES = FemagDesktopWindow._add_master_pages

    def _add_master_pages_with_managerial_dashboard(window) -> None:
        _ORIGINAL_ADD_MASTER_PAGES(window)
        if "managerial_dashboard" not in window._route_indexes:
            window._add_page(
                "managerial_dashboard",
                ManagerialDashboardPage(parent=window),
            )

    FemagDesktopWindow._add_master_pages = _add_master_pages_with_managerial_dashboard
    _INSTALLED = True


def uninstall_managerial_dashboard_extension() -> None:
    """Restore the original shell state; intended for isolated UI tests."""
    global _INSTALLED, _ORIGINAL_ADD_MASTER_PAGES
    set_managerial_dashboard_menu_enabled(False)
    if not _INSTALLED:
        return

    from app.ui.desktop_app import FemagDesktopWindow

    if _ORIGINAL_ADD_MASTER_PAGES is not None:
        FemagDesktopWindow._add_master_pages = _ORIGINAL_ADD_MASTER_PAGES
    _ORIGINAL_ADD_MASTER_PAGES = None
    _INSTALLED = False

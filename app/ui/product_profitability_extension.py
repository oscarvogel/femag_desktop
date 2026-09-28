from app.services.permission_service import PermissionService


_INSTALLED = False
_ORIGINAL = None


def install_product_profitability_extension():
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.product_profitability import ProductProfitabilityPage
    _ORIGINAL = FemagDesktopWindow._add_master_pages

    def wrapped(window):
        _ORIGINAL(window)
        if PermissionService().is_administrator(window.user) and "product_profitability" not in window._route_indexes:
            window._add_page("product_profitability", ProductProfitabilityPage(user=window.user, parent=window))
    FemagDesktopWindow._add_master_pages = wrapped
    _INSTALLED = True

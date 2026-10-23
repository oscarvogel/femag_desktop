"""Registro de la pantalla "Envío de lista de precios" (#705, Fase B, etapa 3).

Se registra como extensión, igual que la rentabilidad por producto: así la ventana principal
no crece con cada pantalla nueva.

La página va envuelta en un área desplazable porque es más alta que la pantalla del cliente
(1638×969 y 1366×768): sin scroll, Qt comprime los layouts y los widgets se superponen
(lo que pasó en #748).
"""

from app.ui.desktop_app import _scrollable_page

_INSTALLED = False
_ORIGINAL = None


def install_price_list_send_extension() -> None:
    global _INSTALLED, _ORIGINAL
    if _INSTALLED:
        return
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.price_list_send_page import PriceListSendPage

    _ORIGINAL = FemagDesktopWindow._add_master_pages

    def wrapped(window):
        _ORIGINAL(window)
        if "price_list_send" not in window._route_indexes:
            window._add_page(
                "price_list_send",
                _scrollable_page(
                    PriceListSendPage(
                        user=window.user,
                        current_user=window.shell.username,
                        parent=window,
                    ),
                    "priceListSendScrollArea",
                ),
            )

    FemagDesktopWindow._add_master_pages = wrapped
    _INSTALLED = True

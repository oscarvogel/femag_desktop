from __future__ import annotations

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QPushButton

from app.ui import desktop_app
from app.ui.form_feedback import FormFeedback


_REFRESH_INTERVAL_MS = 10_000
_installed = False


def install_multi_station_refresh_extension() -> None:
    """Install a centralized refresh policy for multi-workstation FEMAG sessions.

    Screens that expose ``refresh()`` are reloaded when the user navigates to them
    and periodically while they are visible. Legacy screens that already refresh
    internally (notably load orders) are adapted without duplicating their data
    rendering logic.
    """

    global _installed
    if _installed:
        return
    _installed = True

    window_class = desktop_app.FemagDesktopWindow
    original_init = window_class.__init__
    original_load_order_page = window_class._load_order_page
    original_refresh_route = window_class._refresh_route

    def _safe_refresh_route(self, route: str) -> None:
        try:
            original_refresh_route(self, route)
        except Exception as exc:
            page_index = self._route_indexes.get(route)
            page = self.stack.widget(page_index) if page_index is not None else None
            feedback = page.findChild(FormFeedback) if page is not None else None
            if feedback is not None:
                feedback.show_error(
                    f"No se pudo actualizar la información desde la base de datos: {exc}"
                )

    def _load_order_page(self):
        page = original_load_order_page(self)
        search_button = page.findChild(QPushButton, "searchLoadOrderButton")

        def refresh() -> None:
            # The load-order page owns a local refresh closure. Triggering the
            # existing search action with the current text reuses that closure,
            # preserves the filter/selection and forces a fresh MySQL query.
            if search_button is not None and search_button.isEnabled():
                search_button.click()

        page.refresh = refresh
        return page

    def _init(self, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        timer = QTimer(self)
        timer.setInterval(_REFRESH_INTERVAL_MS)
        timer.timeout.connect(lambda: _refresh_visible_route(self))
        timer.start()
        self._multi_station_refresh_timer = timer

    window_class.__init__ = _init
    window_class._load_order_page = _load_order_page
    window_class._refresh_route = _safe_refresh_route


def _refresh_visible_route(window) -> None:
    if not window.isVisible():
        return
    route = getattr(window, "_current_route", None)
    if not route:
        return
    page_index = window._route_indexes.get(route)
    if page_index is None:
        return
    page = window.stack.widget(page_index)
    if page is None or not page.isVisible():
        return
    window._refresh_route(route)

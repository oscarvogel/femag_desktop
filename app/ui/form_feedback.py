from __future__ import annotations

from typing import Literal

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication, QLabel, QWidget


FeedbackKind = Literal["info", "success", "warning", "error"]


_FEEDBACK_STYLES: dict[FeedbackKind, tuple[str, str, str, str, str]] = {
    "info": ("Información", "ⓘ", "#eff6ff", "#60a5fa", "#1e3a8a"),
    "success": ("Éxito", "✓", "#ecfdf3", "#4ade80", "#166534"),
    "warning": ("Atención", "!", "#fffbeb", "#f6c453", "#92400e"),
    "error": ("Error", "×", "#fef2f2", "#f87171", "#991b1b"),
}


class FormFeedback(QLabel):
    """Semantic non-modal toast feedback for FEMAG forms.

    Every ``FormFeedback`` is rendered as a lightweight toast attached to the
    top-level window that owns the form. This keeps success, information,
    warning and non-blocking error messages out of the layout and avoids
    independent windows that the operator must close manually.
    """

    TOAST_TIMEOUT_MS = 3000

    def __init__(self, object_name: str = "formFeedback", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setAccessibleName("Mensaje del formulario")
        self._message = ""
        self._kind: FeedbackKind = "info"
        self._floating_toast = False
        # The feedback widget can be reparented from a form layout to its
        # top-level window when it becomes a floating toast.  Qt may destroy
        # QObject children during that transition, so create the timer only
        # after the final toast parent has been established.
        self._dismiss_timer: QTimer | None = None
        self.hide()

    @property
    def message(self) -> str:
        return self._message

    @property
    def kind(self) -> FeedbackKind:
        return self._kind

    @property
    def is_floating_toast(self) -> bool:
        return self._floating_toast

    def _resolve_host(self) -> QWidget | None:
        parent = self.parentWidget()
        if parent is not None:
            host = parent.window()
            if host is not self:
                return host

        app = QApplication.instance()
        if app is None:
            return None
        host = app.activeWindow()
        if host is None and app.focusWidget() is not None:
            host = app.focusWidget().window()
        return host

    def _ensure_toast_parent(self) -> None:
        host = self._resolve_host()
        if host is None:
            return
        if self.parentWidget() is not host:
            self.setParent(host)
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._floating_toast = True

    def _ensure_dismiss_timer(self) -> QTimer:
        timer = self._dismiss_timer
        if timer is not None:
            try:
                timer.isActive()
                return timer
            except RuntimeError:
                # Its C++ object was deleted while the feedback widget changed
                # parent.  Drop the stale Python wrapper and recreate it.
                pass
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self.clear_message)
        self._dismiss_timer = timer
        return timer

    def _stop_dismiss_timer(self) -> None:
        timer = self._dismiss_timer
        if timer is None:
            return
        try:
            timer.stop()
        except RuntimeError:
            self._dismiss_timer = None

    def _position_toast(self) -> None:
        if not self._floating_toast:
            return
        host = self.parentWidget()
        if host is None:
            return
        available_width = max(host.width() - 48, 220)
        self.setMaximumWidth(min(420, available_width))
        self.adjustSize()
        x = max(16, host.width() - self.width() - 24)
        self.move(x, 0)
        self.raise_()

    def show_message(
        self,
        message: str,
        kind: FeedbackKind = "info",
        *,
        focus_widget: QWidget | None = None,
    ) -> None:
        clean_message = message.strip()
        if not clean_message:
            self.clear_message()
            return
        if kind not in _FEEDBACK_STYLES:
            raise ValueError(f"Tipo de feedback no soportado: {kind}")

        self._ensure_toast_parent()
        timer = self._ensure_dismiss_timer()
        timer.stop()

        title, icon, background, border, foreground = _FEEDBACK_STYLES[kind]
        self._message = clean_message
        self._kind = kind
        self.setProperty("feedbackKind", kind)
        self.setAccessibleDescription(f"{title}: {clean_message}")
        super().setText(f"{icon}  {clean_message}")
        self.setStyleSheet(
            "QLabel {"
            f"background-color: {background};"
            f"border: 1px solid {border};"
            f"border-left: 4px solid {border};"
            "border-radius: 7px;"
            f"color: {foreground};"
            "font-size: 13px;"
            "font-weight: 600;"
            "padding: 9px 11px;"
            "}"
        )
        self.show()
        self._position_toast()
        if self._floating_toast:
            timer.start(self.TOAST_TIMEOUT_MS)
        if focus_widget is not None:
            focus_widget.setFocus()

    def show_info(self, message: str, *, focus_widget: QWidget | None = None) -> None:
        self.show_message(message, "info", focus_widget=focus_widget)

    def show_success(self, message: str, *, focus_widget: QWidget | None = None) -> None:
        self.show_message(message, "success", focus_widget=focus_widget)

    def show_warning(self, message: str, *, focus_widget: QWidget | None = None) -> None:
        self.show_message(message, "warning", focus_widget=focus_widget)

    def show_error(self, message: str, *, focus_widget: QWidget | None = None) -> None:
        self.show_message(message, "error", focus_widget=focus_widget)

    def clear_message(self) -> None:
        self._stop_dismiss_timer()
        self._message = ""
        self.setAccessibleDescription("")
        super().clear()
        self.hide()

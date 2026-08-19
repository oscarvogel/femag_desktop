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
    """Visible, semantic feedback for FEMAG forms.

    Normal instances are rendered inline by the layout that owns them. If a
    feedback label is accidentally created without a parent/layout, it is
    converted into a lightweight toast attached to the active application
    window instead of becoming an independent top-level window.
    """

    FLOATING_TOAST_TIMEOUT_MS = 3000

    def __init__(self, object_name: str = "formFeedback", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setAccessibleName("Mensaje del formulario")
        self._message = ""
        self._kind: FeedbackKind = "info"
        self._floating_toast = False
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.clear_message)
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

    def _ensure_host_parent(self) -> None:
        if self.parentWidget() is not None:
            return
        app = QApplication.instance()
        if app is None:
            return
        host = app.activeWindow()
        if host is None and app.focusWidget() is not None:
            host = app.focusWidget().window()
        if host is None:
            return
        self.setParent(host)
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._floating_toast = True

    def _position_floating_toast(self) -> None:
        if not self._floating_toast:
            return
        host = self.parentWidget()
        if host is None:
            return
        available_width = max(host.width() - 48, 220)
        self.setMaximumWidth(min(420, available_width))
        self.adjustSize()
        x = max(16, host.width() - self.width() - 24)
        self.move(x, 24)
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

        self._dismiss_timer.stop()
        self._ensure_host_parent()

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
        self._position_floating_toast()
        if self._floating_toast:
            self._dismiss_timer.start(self.FLOATING_TOAST_TIMEOUT_MS)
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
        self._dismiss_timer.stop()
        self._message = ""
        self.setAccessibleDescription("")
        super().clear()
        self.hide()

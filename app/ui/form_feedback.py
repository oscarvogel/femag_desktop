from __future__ import annotations

from typing import Literal

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QWidget


FeedbackKind = Literal["info", "success", "warning", "error"]


_FEEDBACK_STYLES: dict[FeedbackKind, tuple[str, str, str, str, str]] = {
    "info": ("Información", "ⓘ", "#eff6ff", "#60a5fa", "#1e3a8a"),
    "success": ("Éxito", "✓", "#ecfdf3", "#4ade80", "#166534"),
    "warning": ("Atención", "!", "#fffbeb", "#f6c453", "#92400e"),
    "error": ("Error", "×", "#fef2f2", "#f87171", "#991b1b"),
}


class FormFeedback(QLabel):
    """Visible, semantic inline feedback for FEMAG forms."""

    def __init__(self, object_name: str = "formFeedback", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setAccessibleName("Mensaje del formulario")
        self._message = ""
        self._kind: FeedbackKind = "info"
        self.hide()

    @property
    def message(self) -> str:
        return self._message

    @property
    def kind(self) -> FeedbackKind:
        return self._kind

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
        self._message = ""
        self.setAccessibleDescription("")
        super().clear()
        self.hide()

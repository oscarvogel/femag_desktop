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

    The label remains owned by the page/dialog that created it. On first use it
    is detached from that parent's layout and positioned as a floating child.
    Keeping the same QObject parent is important: reparenting a live PyQt widget
    can invalidate C++ children and produce hard interpreter aborts in offscreen
    environments as well as intermittent workstation crashes.
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
        self._dismiss_generation = 0
        self._toast_host: QWidget | None = None
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
            return parent

        app = QApplication.instance()
        if app is None:
            return None
        host = app.activeWindow()
        if host is None and app.focusWidget() is not None:
            host = app.focusWidget().window()
        return host

    def _ensure_toast_parent(self) -> None:
        if self._floating_toast:
            return
        host = self._resolve_host()
        if host is None:
            return

        # In normal FEMAG forms ``layout.addWidget`` has already assigned the
        # feedback label to its page/dialog. Detach it from geometry management
        # without changing the QObject parent so it can float safely.
        if self.parentWidget() is None:
            self.setParent(host)
        layout = host.layout()
        if layout is not None:
            layout.removeWidget(self)

        self._toast_host = host
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._floating_toast = True

    def _schedule_dismiss(self) -> None:
        self._dismiss_generation += 1
        generation = self._dismiss_generation
        QTimer.singleShot(
            self.TOAST_TIMEOUT_MS,
            lambda: self._clear_if_generation(generation),
        )

    def _clear_if_generation(self, generation: int) -> None:
        if generation == self._dismiss_generation:
            self.clear_message()

    def _position_toast(self) -> None:
        if not self._floating_toast:
            return
        host = self._toast_host or self.parentWidget()
        if host is None:
            return
        available_width = max(host.width() - 32, 220)
        self.setMaximumWidth(min(420, available_width))
        self.adjustSize()
        x = max(8, host.width() - self.width() - 16)
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
        self._dismiss_generation += 1

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
            self._schedule_dismiss()
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
        self._dismiss_generation += 1
        self._message = ""
        self.setAccessibleDescription("")
        super().clear()
        self.hide()

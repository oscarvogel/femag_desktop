"""Comportamiento común de teclado para formularios FEMAG.

Acepta punto o coma en controles decimales y evita que Enter dispare
acciones por defecto mientras el usuario está recorriendo un formulario.
"""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QDoubleValidator, QKeyEvent, QValidator
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QLineEdit,
    QPushButton,
    QWidget,
)


_DECIMAL_KEYS = {Qt.Key_Comma, Qt.Key_Period}
_ENTER_KEYS = {Qt.Key_Enter, Qt.Key_Return}


def _ancestor(widget: QWidget, widget_type):
    current = widget.parentWidget()
    while current is not None:
        if isinstance(current, widget_type):
            return current
        current = current.parentWidget()
    return None


def _spinbox_for(widget: QWidget) -> QAbstractSpinBox | None:
    if isinstance(widget, QAbstractSpinBox):
        return widget
    if isinstance(widget, QLineEdit):
        parent = widget.parentWidget()
        if isinstance(parent, QAbstractSpinBox):
            return parent
    return None


def _combo_for(widget: QWidget) -> QComboBox | None:
    if isinstance(widget, QComboBox):
        return widget
    if isinstance(widget, QLineEdit):
        parent = widget.parentWidget()
        if isinstance(parent, QComboBox):
            return parent
    return None


def _decimal_editor(widget: QWidget):
    """Devuelve (line_edit, validator, separator) para una entrada decimal."""
    spinbox = _spinbox_for(widget)
    if spinbox is not None and hasattr(spinbox, "decimals"):
        editor = spinbox.lineEdit()
        return editor, spinbox, spinbox.locale().decimalPoint()

    if isinstance(widget, QLineEdit):
        validator = widget.validator()
        if isinstance(validator, QDoubleValidator):
            return widget, validator, validator.locale().decimalPoint()
    return None


def _candidate_text(editor: QLineEdit, inserted: str) -> tuple[str, int]:
    text = editor.text()
    start = editor.selectionStart()
    if start >= 0:
        selection_length = len(editor.selectedText())
        candidate = text[:start] + inserted + text[start + selection_length :]
        return candidate, start + len(inserted)
    position = editor.cursorPosition()
    candidate = text[:position] + inserted + text[position:]
    return candidate, position + len(inserted)


def _insert_decimal_separator(widget: QWidget) -> bool:
    decimal = _decimal_editor(widget)
    if decimal is None:
        return False

    editor, validator, separator = decimal
    candidate, position = _candidate_text(editor, separator)
    state, _text, _position = validator.validate(candidate, position)
    if state == QValidator.Invalid:
        return True

    editor.insert(separator)
    return True


def _canonical_input(widget: QWidget) -> QWidget | None:
    spinbox = _spinbox_for(widget)
    if spinbox is not None:
        return spinbox

    combo = _combo_for(widget)
    if combo is not None:
        return combo

    if isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.Normal:
        return widget
    return None


def _is_data_entry(widget: QWidget) -> bool:
    if not widget.isEnabled() or not widget.isVisible():
        return False
    if isinstance(widget, QAbstractSpinBox):
        return not widget.isReadOnly()
    if isinstance(widget, QComboBox):
        return widget.isEditable() or widget.count() > 0
    if isinstance(widget, QLineEdit):
        return not widget.isReadOnly() and widget.echoMode() == QLineEdit.Normal
    return False


def _next_data_entry(source: QWidget) -> QWidget | None:
    """Busca el siguiente campo editable sin caer en botones de acción.

    Si después del último campo aparece un botón (Guardar/Aceptar/etc.),
    se detiene: Enter no debe convertir accidentalmente una carga en una
    confirmación.
    """
    current = source.nextInFocusChain()
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        candidate = _canonical_input(current)
        if candidate is source:
            return None
        if isinstance(current, QPushButton):
            return None
        if candidate is not None and candidate is not source and _is_data_entry(candidate):
            return candidate
        current = current.nextInFocusChain()
    return None


def _should_navigate_with_enter(widget: QWidget) -> bool:
    source = _canonical_input(widget)
    if source is None:
        return False

    # Un combo con el desplegable abierto usa Enter para confirmar la opción.
    if isinstance(source, QComboBox) and source.view().isVisible():
        return False

    # Los spinboxes son entradas operativas incluso en páginas embebidas.
    if isinstance(source, QAbstractSpinBox):
        return True

    # Para QLineEdit/QComboBox limitamos la navegación a formularios/diálogos.
    # Así se preservan acciones explícitas de páginas como el buscador global.
    return isinstance(source, QDialog) or _ancestor(source, QDialog) is not None


class FormInputBehavior(QObject):
    """Filtro global y conservador para entradas de formularios FEMAG."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API Qt
        if event.type() != QEvent.KeyPress or not isinstance(event, QKeyEvent):
            return False
        if not isinstance(watched, QWidget):
            return False

        if event.key() in _DECIMAL_KEYS or event.text() in {".", ","}:
            if _insert_decimal_separator(watched):
                event.accept()
                return True

        if event.key() in _ENTER_KEYS and _should_navigate_with_enter(watched):
            source = _canonical_input(watched)
            if source is None:
                return False
            target = _next_data_entry(source)
            if target is not None:
                target.setFocus(Qt.TabFocusReason)
                if isinstance(target, QLineEdit):
                    target.selectAll()
            event.accept()
            return True

        return False


def install_form_input_behavior(app: QApplication | None = None) -> FormInputBehavior:
    """Instala una sola instancia del filtro en la QApplication activa."""
    qt_app = app or QApplication.instance()
    if qt_app is None:
        raise RuntimeError("QApplication debe existir antes de instalar el comportamiento de formularios.")

    existing = getattr(qt_app, "_femag_form_input_behavior", None)
    if isinstance(existing, FormInputBehavior):
        return existing

    behavior = FormInputBehavior(qt_app)
    qt_app.installEventFilter(behavior)
    qt_app._femag_form_input_behavior = behavior
    return behavior

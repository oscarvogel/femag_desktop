from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


AUTOCOMPLETE_PROPERTY = "femagAutocompleteEnabled"
DEFAULT_HINT = "Clic para ver la lista, escribí para filtrar"


class _PopupToggleFilter(QObject):
    """Open or close the combo popup when the editable field is clicked."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo = combo

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.MouseButtonPress and watched is self._combo.lineEdit():
            if self._popup_is_visible():
                self._close_popup()
            else:
                self._open_filtered_popup()
        return False

    def _popup_is_visible(self) -> bool:
        if self._combo.view().isVisible():
            return True
        completer = self._combo.completer()
        return completer is not None and completer.popup().isVisible()

    def _close_popup(self) -> None:
        completer = self._combo.completer()
        if completer is not None and completer.popup().isVisible():
            completer.popup().hide()
        self._combo.hidePopup()

    def _open_filtered_popup(self) -> None:
        text = self._combo.lineEdit().text()
        completer = self._combo.completer()
        if text and completer is not None:
            completer.setCompletionPrefix(text)
            completer.complete()
        else:
            self._combo.showPopup()


def enable_combo_autocomplete(
    combo: QComboBox,
    *,
    placeholder: str = "Buscar...",
    hint: str = DEFAULT_HINT,
) -> QComboBox:
    """Make a combo searchable without allowing arbitrary values to be stored."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMaxVisibleItems(12)

    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setClearButtonEnabled(True)
        line_edit.setPlaceholderText(placeholder)
        if hint:
            line_edit.setToolTip(hint)

    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    combo.setCompleter(completer)

    if not combo.property(AUTOCOMPLETE_PROPERTY) and line_edit is not None:
        line_edit.installEventFilter(_PopupToggleFilter(combo))
        line_edit.editingFinished.connect(lambda current=combo: commit_combo_text(current))
        combo.setProperty(AUTOCOMPLETE_PROPERTY, True)
    return combo


def matching_combo_index(combo: QComboBox, text: str) -> int:
    normalized = text.strip().casefold()
    for index in range(combo.count()):
        if combo.itemText(index).strip().casefold() == normalized:
            return index
    return -1


def commit_combo_text(combo: QComboBox) -> None:
    """Commit an exact label or clear text that is not one of the available items."""
    index = matching_combo_index(combo, combo.currentText())
    if index >= 0:
        combo.setCurrentIndex(index)
        return
    combo.setCurrentIndex(-1)
    combo.clearEditText()


def combo_current_data(combo: QComboBox):
    """Return data only when the visible text identifies an actual combo item."""
    index = matching_combo_index(combo, combo.currentText())
    return combo.itemData(index) if index >= 0 else None

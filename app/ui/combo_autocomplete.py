from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QCompleter


AUTOCOMPLETE_PROPERTY = "femagAutocompleteEnabled"


def enable_combo_autocomplete(combo: QComboBox, *, placeholder: str = "Buscar...") -> QComboBox:
    """Make a combo searchable without allowing arbitrary values to be stored."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.setMaxVisibleItems(12)

    line_edit = combo.lineEdit()
    if line_edit is not None:
        line_edit.setClearButtonEnabled(True)
        line_edit.setPlaceholderText(placeholder)

    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    combo.setCompleter(completer)

    if not combo.property(AUTOCOMPLETE_PROPERTY) and line_edit is not None:
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

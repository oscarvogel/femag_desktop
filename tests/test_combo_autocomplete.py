from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QComboBox

from app.ui.combo_autocomplete import combo_current_data, enable_combo_autocomplete


_APP = None


def _application() -> QApplication:
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _combo() -> QComboBox:
    _application()
    combo = QComboBox()
    combo.addItem("", None)
    combo.addItem("Cliente Norte", 10)
    combo.addItem("Distribuidora del Sur", 20)
    enable_combo_autocomplete(combo)
    return combo


def test_combo_filters_by_partial_text_case_insensitive() -> None:
    combo = _combo()
    combo.completer().setCompletionPrefix("SUR")

    assert combo.completer().filterMode() == Qt.MatchContains
    assert combo.completer().caseSensitivity() == Qt.CaseInsensitive
    assert combo.completer().completionModel().rowCount() == 1
    assert combo.completer().completionModel().index(0, 0).data() == "Distribuidora del Sur"


def test_combo_preserves_data_when_exact_item_is_typed() -> None:
    combo = _combo()
    combo.setEditText("cliente norte")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentText() == "Cliente Norte"
    assert combo.currentData() == 10
    assert combo_current_data(combo) == 10


def test_combo_clears_text_that_is_not_an_available_item() -> None:
    combo = _combo()
    combo.setCurrentIndex(1)
    combo.setEditText("cliente inventado")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentIndex() == -1
    assert combo.currentText() == ""
    assert combo.currentData() is None

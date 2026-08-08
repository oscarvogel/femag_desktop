from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
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


def _show(combo: QComboBox) -> QComboBox:
    combo.show()
    _application().processEvents()
    return combo


def test_combo_click_on_field_opens_popup() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert combo.view().isVisible()


def test_combo_click_again_closes_popup() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert combo.view().isVisible()
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    assert not combo.view().isVisible()


def test_combo_sets_deploy_hint_tooltip() -> None:
    combo = _combo()
    assert combo.lineEdit().toolTip() == "Clic para ver la lista, escribí para filtrar"


def test_combo_accepts_custom_hint() -> None:
    _application()
    combo = QComboBox()
    combo.addItem("A", 1)
    enable_combo_autocomplete(combo, hint="Toque para desplegar")
    assert combo.lineEdit().toolTip() == "Toque para desplegar"


def test_combo_filters_after_opening_via_click() -> None:
    combo = _show(_combo())
    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    _application().processEvents()
    combo.completer().setCompletionPrefix("SUR")
    assert combo.completer().completionModel().rowCount() == 1
    assert combo.completer().completionModel().index(0, 0).data() == "Distribuidora del Sur"

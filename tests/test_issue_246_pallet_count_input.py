import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_pallet_count_starts_empty_and_adds_exact_entered_value():
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=[])
    widget.show()
    app.processEvents()

    count_input = widget.bulk_pallet_count_input

    assert count_input.value() == 0
    # Qt 5.15 no aplica setSpecialValueText(""); usamos " " para que el input
    # se vea vacío. Aceptamos "" o " " como "input visualmente vacío".
    assert count_input.text() in ("", " ")

    count_input.setValue(9)
    widget.add_pallet_button.click()
    app.processEvents()

    assert len(widget.pallet_drafts()) == 9
    assert [pallet["sequence"] for pallet in widget.pallet_drafts()] == list(range(1, 10))
    assert count_input.value() == 0
    assert count_input.text() in ("", " ")
    assert count_input.hasFocus()

    widget.close()


def test_empty_pallet_count_does_not_create_a_pallet_and_keeps_focus():
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=[])
    widget.show()
    app.processEvents()

    widget.add_pallet_button.click()
    app.processEvents()

    assert widget.pallet_drafts() == []
    assert widget.bulk_pallet_count_input.text() in ("", " ")
    assert widget.bulk_pallet_count_input.hasFocus()

    widget.close()

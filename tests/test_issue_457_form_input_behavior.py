import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QEvent, QLocale, Qt
from PyQt5.QtGui import QDoubleValidator, QKeyEvent
from PyQt5.QtWidgets import QApplication, QDialog, QDoubleSpinBox, QLineEdit, QPushButton, QVBoxLayout

from app.ui.form_input_behavior import install_form_input_behavior


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    existing = getattr(app, "_femag_form_input_behavior", None)
    behavior = install_form_input_behavior(app)
    try:
        yield app
    finally:
        if existing is None:
            app.removeEventFilter(behavior)
            if getattr(app, "_femag_form_input_behavior", None) is behavior:
                delattr(app, "_femag_form_input_behavior")


def _send_key(app, widget, key, text=""):
    event = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text)
    QApplication.sendEvent(widget, event)
    app.processEvents()


@pytest.mark.parametrize(
    ("key", "text"),
    [
        (Qt.Key_Period, "."),
        (Qt.Key_Comma, ","),
    ],
)
def test_decimal_spinbox_accepts_dot_and_comma_with_comma_locale(qt_app, key, text):
    spin = QDoubleSpinBox()
    spin.setLocale(QLocale(QLocale.Spanish, QLocale.Argentina))
    spin.setDecimals(2)
    spin.setRange(0, 9999)
    editor = spin.lineEdit()
    editor.setText("12")
    editor.setCursorPosition(len(editor.text()))

    _send_key(qt_app, editor, key, text)
    _send_key(qt_app, editor, Qt.Key_5, "5")
    spin.interpretText()

    assert spin.value() == pytest.approx(12.5)


@pytest.mark.parametrize(
    ("key", "text"),
    [
        (Qt.Key_Period, "."),
        (Qt.Key_Comma, ","),
    ],
)
def test_double_validator_line_edit_accepts_dot_and_comma(qt_app, key, text):
    line = QLineEdit()
    validator = QDoubleValidator(0.0, 9999.0, 2, line)
    validator.setLocale(QLocale(QLocale.Spanish, QLocale.Argentina))
    line.setValidator(validator)
    line.setText("12")
    line.setCursorPosition(2)

    _send_key(qt_app, line, key, text)
    _send_key(qt_app, line, Qt.Key_5, "5")

    assert line.text() == "12,5"


def test_enter_moves_to_next_field_without_triggering_default_button(qt_app):
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    first = QLineEdit()
    second = QLineEdit()
    save = QPushButton("Guardar")
    save.setDefault(True)
    save.clicked.connect(dialog.accept)
    layout.addWidget(first)
    layout.addWidget(second)
    layout.addWidget(save)
    dialog.show()
    qt_app.processEvents()

    first.setFocus()
    _send_key(qt_app, first, Qt.Key_Return, "\r")

    assert second.hasFocus()
    assert dialog.result() != QDialog.Accepted

    _send_key(qt_app, second, Qt.Key_Return, "\r")

    assert dialog.result() != QDialog.Accepted
    assert not save.hasFocus()
    dialog.close()


def test_enter_keeps_explicit_page_action_outside_dialog(qt_app):
    line = QLineEdit()
    triggered = []
    line.returnPressed.connect(lambda: triggered.append(True))
    line.show()
    line.setFocus()
    qt_app.processEvents()

    _send_key(qt_app, line, Qt.Key_Return, "\r")

    assert triggered == [True]
    line.close()

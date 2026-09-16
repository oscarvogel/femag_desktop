from pathlib import Path

import pytest
from PyQt5.QtWidgets import QDoubleSpinBox

from app.ui.money import MONEY_MAX, configure_money_input


NINE_DIGIT_AMOUNT = 123_456_789.50


def test_common_money_input_accepts_nine_digit_amount(qtbot):
    widget = QDoubleSpinBox()
    qtbot.addWidget(widget)

    configure_money_input(widget)
    widget.setValue(NINE_DIGIT_AMOUNT)

    assert widget.value() == pytest.approx(NINE_DIGIT_AMOUNT, abs=0.01)
    assert widget.maximum() == pytest.approx(MONEY_MAX, abs=0.01)


@pytest.mark.parametrize(
    "path",
    [
        "app/ui/customer_payment_dialog.py",
        "app/ui/client_manual_credit_dialog.py",
        "app/ui/client_manual_debit_dialog.py",
        "app/ui/master_abm.py",
        "app/ui/desktop_app.py",
    ],
)
def test_money_screens_use_common_money_policy(path):
    source = Path(path).read_text(encoding="utf-8")

    assert "configure_money_input" in source


def test_known_legacy_money_caps_are_not_reintroduced():
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "app/ui/customer_payment_dialog.py",
            "app/ui/client_manual_credit_dialog.py",
            "app/ui/client_manual_debit_dialog.py",
            "app/ui/master_abm.py",
            "app/ui/desktop_app.py",
        )
    )

    assert "99999999.99" not in sources
    assert "99999999)" not in sources
    assert "999_999_999.99" not in sources
    assert "9999999999.99" not in sources

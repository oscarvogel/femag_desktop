"""Configuración común para entradas monetarias de FEMAG."""

from __future__ import annotations

from PyQt5.QtWidgets import QDoubleSpinBox


MONEY_MAX = 9_999_999_999_999.99


def configure_money_input(
    widget: QDoubleSpinBox,
    *,
    minimum: float = 0.0,
    maximum: float = MONEY_MAX,
    decimals: int = 2,
    step: float = 100.0,
    prefix: str = "$ ",
) -> QDoubleSpinBox:
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setSingleStep(step)
    widget.setPrefix(prefix)
    return widget

"""Selector buscable de localidades DGR para las pantallas de domicilios/F150."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox

from app.services.f150_dgr_service import F150DgrCorrectionService


def create_locality_combo(
    *, object_name: str, current_id: int | None = None
) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName(object_name)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.lineEdit().setPlaceholderText(
        "Buscar localidad DGR por nombre, codigo o provincia"
    )
    for locality in F150DgrCorrectionService.localities():
        combo.addItem(F150DgrCorrectionService.locality_label(locality), locality.id)
    completer = combo.completer()
    if completer is not None:
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
    if current_id is not None:
        index = combo.findData(current_id)
        if index >= 0:
            combo.setCurrentIndex(index)
    return combo


def selected_locality_id(combo: QComboBox) -> int | None:
    data = combo.currentData()
    return int(data) if data is not None else None

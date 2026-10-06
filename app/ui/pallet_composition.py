from __future__ import annotations

from PyQt5.QtWidgets import QHeaderView, QSizePolicy

from app.ui.pallet_composition_guided_impl import (
    PalletCompositionWidget as _GuidedPalletCompositionWidget,
)
from app.ui.pallet_composition_legacy import PalletCard, _kg_text, _quantity_text


class PalletCompositionWidget(_GuidedPalletCompositionWidget):
    """Fachada publica del workbench guiado con compatibilidad legacy."""

    def _install_guided_workbench(self) -> None:
        super()._install_guided_workbench()

        # La tabla de pendientes venia del editor anterior con varias columnas
        # ResizeToContents. En el workbench principal eso infla el sizeHint del
        # widget por encima del ancho de una notebook de 1280 px. En esta vista
        # todas las columnas pueden repartirse el ancho disponible.
        pending_header = self.pending_table.horizontalHeader()
        pending_header.setMinimumSectionSize(40)
        pending_header.setSectionResizeMode(QHeaderView.Stretch)
        self.pending_table.setMinimumWidth(0)
        self.pending_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        current_header = self.guided_content_table.horizontalHeader()
        current_header.setMinimumSectionSize(40)
        current_header.setSectionResizeMode(QHeaderView.Stretch)
        self.guided_content_table.setMinimumWidth(0)
        self.guided_content_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        for group in (self.guided_splitter.widget(0), self.guided_splitter.widget(1)):
            group.setMinimumWidth(0)
            group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        for button in (
            self.guided_add_button,
            self.guided_partial_button,
            self.guided_auto_button,
            self.guided_propose_rest_button,
            self.guided_new_pallet_button,
            self.guided_remove_button,
            self.guided_lock_button,
            self.guided_advanced_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.guided_pallet_combo.setMinimumWidth(0)
        self.guided_pallet_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.guided_splitter.setMinimumWidth(0)
        self.guided_splitter.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)


__all__ = [
    "PalletCard",
    "PalletCompositionWidget",
    "_kg_text",
    "_quantity_text",
]

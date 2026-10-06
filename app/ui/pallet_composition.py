from __future__ import annotations

from PyQt5.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
)

from app.ui.pallet_composition_guided_impl import (
    PalletCompositionWidget as _GuidedPalletCompositionWidget,
)
from app.ui.pallet_composition_legacy import PalletCard, _kg_text, _quantity_text


class PalletCompositionWidget(_GuidedPalletCompositionWidget):
    """Fachada publica del workbench guiado con compatibilidad legacy."""

    def _install_guided_workbench(self) -> None:
        super()._install_guided_workbench()

        # El operador normalmente conoce el total de pallets de la carga. Esta
        # accion completa hasta ese total en vez de sumar N, evitando que una
        # carga con 3 pallets termine accidentalmente con 23 al pedir "20".
        current_group = self.guided_splitter.widget(1)
        current_layout = current_group.layout()
        pallet_count_row = QHBoxLayout()
        pallet_count_row.addWidget(QLabel("Total de pallets:"))
        self.guided_total_pallets_input = QSpinBox()
        self.guided_total_pallets_input.setObjectName("guidedTotalPalletCountInput")
        self.guided_total_pallets_input.setRange(1, 999)
        self.guided_total_pallets_input.setValue(max(len(self._pallets), 1))
        self.guided_total_pallets_input.setMinimumWidth(72)
        self.guided_total_pallets_input.setMaximumWidth(96)
        pallet_count_row.addWidget(self.guided_total_pallets_input)
        self.guided_create_to_total_button = QPushButton("Crear hasta total")
        self.guided_create_to_total_button.setObjectName("guidedCreatePalletsToTotalButton")
        self.guided_create_to_total_button.clicked.connect(self._guided_create_to_total)
        pallet_count_row.addWidget(self.guided_create_to_total_button, 1)
        current_layout.insertLayout(0, pallet_count_row)

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
            self.guided_create_to_total_button,
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

    def _guided_create_to_total(self) -> None:
        target = int(self.guided_total_pallets_input.value())
        current = len(self._pallets)
        if target <= current:
            self.issue_label.show_info(
                f"La composicion ya tiene {current} pallets. No se agregaron pallets."
            )
            return
        self.add_pallets(target - current)
        self.issue_label.show_success(
            f"Se prepararon {target} pallets para la carga."
        )

    def _refresh_guided_ui(self) -> None:
        super()._refresh_guided_ui()
        if hasattr(self, "guided_total_pallets_input"):
            self.guided_total_pallets_input.setValue(max(len(self._pallets), 1))


__all__ = [
    "PalletCard",
    "PalletCompositionWidget",
    "_kg_text",
    "_quantity_text",
]

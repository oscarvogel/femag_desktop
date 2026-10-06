from __future__ import annotations

from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from app.services.pallet_capacity_service import PalletCapacityService
from app.ui.pallet_composition_guided_impl import (
    PalletCompositionWidget as _GuidedPalletCompositionWidget,
)
from app.ui.pallet_composition_legacy import PalletCard, _kg_text, _quantity_text


class PalletCompositionWidget(_GuidedPalletCompositionWidget):
    """Fachada publica del workbench guiado con compatibilidad legacy."""

    PALLET_SELECTOR_COLUMNS = 5

    def _install_guided_workbench(self) -> None:
        super()._install_guided_workbench()

        current_group = self.guided_splitter.widget(1)
        current_layout = current_group.layout()

        # El operador normalmente conoce el total de pallets de la carga. Esta
        # accion completa hasta ese total en vez de sumar N, evitando duplicados.
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

        # La capacidad era parte del panel legacy que ahora esta oculto. Se
        # vuelve a exponer en el flujo principal para que ninguna accion falle
        # silenciosamente por falta de Kg/pallet.
        capacity_row = QHBoxLayout()
        self.guided_capacity_label = QLabel()
        self.guided_capacity_label.setObjectName("guidedPalletCapacityLabel")
        capacity_row.addWidget(self.guided_capacity_label, 1)
        self.configure_pallet_capacity_button.setParent(current_group)
        self.configure_pallet_capacity_button.setText("Configurar Kg/pallet")
        capacity_row.addWidget(self.configure_pallet_capacity_button)
        current_layout.insertLayout(1, capacity_row)

        # El combo sirve tecnicamente, pero con 19/20 pallets es incomodo. Se
        # conserva oculto como sincronizador interno y se reemplaza por una
        # grilla de botones visibles, estilo selector operativo.
        legacy_pallet_row = current_layout.itemAt(2).layout()
        if legacy_pallet_row is not None:
            label_item = legacy_pallet_row.itemAt(0)
            if label_item is not None and label_item.widget() is not None:
                label_item.widget().hide()
        self.guided_pallet_combo.hide()
        self.guided_new_pallet_button.setText("+ Nuevo pallet")

        selector_frame = QFrame(current_group)
        selector_frame.setObjectName("guidedPalletSelectorFrame")
        selector_layout = QHBoxLayout(selector_frame)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.addWidget(QLabel("Pallets:"))
        self.guided_pallet_selector_scroll = QScrollArea(selector_frame)
        self.guided_pallet_selector_scroll.setObjectName("guidedPalletSelectorScroll")
        self.guided_pallet_selector_scroll.setWidgetResizable(True)
        self.guided_pallet_selector_scroll.setFrameShape(QFrame.NoFrame)
        self.guided_pallet_selector_scroll.setMaximumHeight(112)
        self.guided_pallet_selector_container = QWidget()
        self.guided_pallet_selector_grid = QGridLayout(self.guided_pallet_selector_container)
        self.guided_pallet_selector_grid.setContentsMargins(0, 0, 0, 0)
        self.guided_pallet_selector_grid.setSpacing(5)
        self.guided_pallet_selector_scroll.setWidget(self.guided_pallet_selector_container)
        selector_layout.addWidget(self.guided_pallet_selector_scroll, 1)
        current_layout.insertWidget(3, selector_frame)
        self._guided_pallet_buttons: dict[int, QPushButton] = {}

        # El feedback tambien estaba dentro del panel legacy oculto. Reparentarlo
        # hace visibles errores, advertencias y confirmaciones del flujo guiado.
        self.issue_label.setParent(current_group)
        current_layout.insertWidget(max(current_layout.count() - 1, 0), self.issue_label)

        # La tabla de pendientes venia con ResizeToContents y forzaba anchos
        # enormes. En el workbench principal las columnas reparten el espacio.
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
            self.configure_pallet_capacity_button,
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
        self.issue_label.show_success(f"Se prepararon {target} pallets para la carga.")

    def _guided_select_pallet(self, sequence: int) -> None:
        if not any(int(pallet["sequence"]) == int(sequence) for pallet in self._pallets):
            return
        self._selected_sequence = int(sequence)
        self._render_editor()
        self._refresh_guided_ui()

    def _rebuild_guided_pallet_selector(self) -> None:
        while self.guided_pallet_selector_grid.count():
            item = self.guided_pallet_selector_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._guided_pallet_buttons = {}

        for index, pallet in enumerate(sorted(self._pallets, key=lambda item: int(item["sequence"]))):
            sequence = int(pallet["sequence"])
            button = QPushButton(str(sequence))
            button.setObjectName(f"guidedPalletSelectorButton_{sequence}")
            button.setCheckable(True)
            button.setChecked(sequence == self._selected_sequence)
            button.setMinimumWidth(42)
            button.setMaximumHeight(32)
            suffix = " · fijado" if sequence in self._locked_sequences else ""
            button.setToolTip(f"Pallet {sequence}{suffix} · {_kg_text(self._pallet_kg(pallet))}")
            button.clicked.connect(lambda _checked=False, seq=sequence: self._guided_select_pallet(seq))
            row = index // self.PALLET_SELECTOR_COLUMNS
            column = index % self.PALLET_SELECTOR_COLUMNS
            self.guided_pallet_selector_grid.addWidget(button, row, column)
            self._guided_pallet_buttons[sequence] = button

        if not self._pallets:
            empty = QLabel("Todavia no hay pallets. Defina el total o agregue uno.")
            empty.setWordWrap(True)
            self.guided_pallet_selector_grid.addWidget(empty, 0, 0, 1, self.PALLET_SELECTOR_COLUMNS)

    def _refresh_guided_ui(self) -> None:
        super()._refresh_guided_ui()
        if not hasattr(self, "guided_total_pallets_input"):
            return

        self.guided_total_pallets_input.setValue(max(len(self._pallets), 1))
        max_kg = PalletCapacityService.pallet_max_kg()
        if max_kg is None:
            self.guided_capacity_label.setText("Kg/pallet: SIN CONFIGURAR")
            self.guided_capacity_label.setStyleSheet("font-weight: 800; color: #b42318;")
            help_text = "Configure Kg/pallet para agregar, distribuir o proponer mercaderia."
            for button in (
                self.guided_add_button,
                self.guided_partial_button,
                self.guided_auto_button,
                self.guided_propose_rest_button,
            ):
                button.setToolTip(help_text)
        else:
            self.guided_capacity_label.setText(f"Kg/pallet: {_kg_text(max_kg)}")
            self.guided_capacity_label.setStyleSheet("font-weight: 800;")
            for button in (
                self.guided_add_button,
                self.guided_partial_button,
                self.guided_auto_button,
                self.guided_propose_rest_button,
            ):
                button.setToolTip("")

        self._rebuild_guided_pallet_selector()


__all__ = [
    "PalletCard",
    "PalletCompositionWidget",
    "_kg_text",
    "_quantity_text",
]

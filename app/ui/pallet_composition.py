from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from app.services.pallet_capacity_service import PalletCapacityService
from app.ui.form_feedback import FormFeedback
from app.ui.pallet_composition_guided_impl import (
    PalletCompositionWidget as _GuidedPalletCompositionWidget,
)
from app.ui.pallet_composition_legacy import PalletCard, _kg_text, _quantity_text


class PalletCompositionWidget(_GuidedPalletCompositionWidget):
    """Fachada publica del workbench guiado con compatibilidad legacy."""

    PALLET_SELECTOR_COLUMNS = 10

    def _install_guided_workbench(self) -> None:
        super()._install_guided_workbench()

        # Las cuatro acciones sobre mercaderia pendiente forman un unico flujo.
        # La implementacion base dejaba "Proponer resto" en una segunda fila;
        # lo movemos junto a agregar, carga parcial y distribucion automatica.
        pending_group = self.guided_splitter.widget(0)
        pending_layout = pending_group.layout()
        pending_layout.removeWidget(self.guided_propose_rest_button)
        for index in range(pending_layout.count()):
            action_layout = pending_layout.itemAt(index).layout()
            if action_layout is None:
                continue
            if action_layout.indexOf(self.guided_auto_button) >= 0:
                action_layout.addWidget(self.guided_propose_rest_button, 2)
                break

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

        capacity_row = QHBoxLayout()
        self.guided_capacity_label = QLabel()
        self.guided_capacity_label.setObjectName("guidedPalletCapacityLabel")
        self.guided_capacity_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        capacity_row.addWidget(self.guided_capacity_label, 1)
        self.guided_configure_capacity_button = QPushButton("Configurar Kg/pallet")
        self.guided_configure_capacity_button.setObjectName("guidedConfigurePalletCapacityButton")
        self.guided_configure_capacity_button.clicked.connect(self.configure_pallet_capacity)
        self.guided_configure_capacity_button.setMinimumWidth(150)
        self.guided_configure_capacity_button.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Fixed
        )
        capacity_row.addWidget(self.guided_configure_capacity_button)
        current_layout.insertLayout(1, capacity_row)

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
        self.guided_pallet_selector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.guided_pallet_selector_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.guided_pallet_selector_scroll.setMinimumHeight(76)
        self.guided_pallet_selector_scroll.setMaximumHeight(84)
        self.guided_pallet_selector_container = QWidget()
        self.guided_pallet_selector_grid = QGridLayout(self.guided_pallet_selector_container)
        self.guided_pallet_selector_grid.setContentsMargins(0, 0, 0, 0)
        self.guided_pallet_selector_grid.setSpacing(5)
        self.guided_pallet_selector_scroll.setWidget(self.guided_pallet_selector_container)
        selector_layout.addWidget(self.guided_pallet_selector_scroll, 1)
        self.guided_pallet_selector_frame = selector_frame
        self._guided_pallet_buttons: dict[int, QPushButton] = {}

        self.guided_current_pallet_label = QLabel("PALLET ACTUAL: -")
        self.guided_current_pallet_label.setObjectName("guidedCurrentPalletLabel")
        self.guided_current_pallet_label.setStyleSheet(
            "font-size: 15px; font-weight: 900; color: #173a59; padding: 4px 0;"
        )
        current_layout.insertWidget(3, self.guided_current_pallet_label)

        self.guided_delete_pallet_button = QPushButton("Eliminar pallet")
        self.guided_delete_pallet_button.setObjectName("guidedDeletePalletButton")
        self.guided_delete_pallet_button.setProperty("secondary", True)
        self.guided_delete_pallet_button.clicked.connect(self._guided_delete_current_pallet)
        current_layout.insertWidget(4, self.guided_delete_pallet_button)

        self._legacy_issue_label = self.issue_label
        self.guided_feedback = FormFeedback("guidedPalletFeedback", current_group)
        self.issue_label = self.guided_feedback
        current_layout.insertWidget(max(current_layout.count() - 1, 0), self.guided_feedback)

        pending_header = self.pending_table.horizontalHeader()
        pending_header.setMinimumSectionSize(40)
        pending_header.setSectionResizeMode(QHeaderView.Stretch)
        self.pending_table.setMinimumWidth(0)
        self.pending_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        current_header = self.guided_content_table.horizontalHeader()
        current_header.setMinimumSectionSize(40)
        current_header.setSectionResizeMode(QHeaderView.Stretch)
        self.guided_content_table.setMinimumWidth(0)
        self.guided_content_table.setMinimumHeight(150)
        self.guided_content_table.setMaximumHeight(260)
        self.guided_content_table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        advanced_index = current_layout.indexOf(self.guided_advanced_button)
        current_layout.insertWidget(max(advanced_index, 0), selector_frame)

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
            self.guided_delete_pallet_button,
            self.guided_remove_button,
            self.guided_lock_button,
            self.guided_advanced_button,
        ):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        # La carga parcial es parte del flujo principal: debe permanecer visible
        # para repartir manualmente una linea entre varios pallets.
        self.guided_partial_button.setText("Agregar cantidad...")
        self.guided_partial_button.setMinimumWidth(160)
        self.guided_partial_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.guided_partial_button.show()
        self.guided_propose_rest_button.setMinimumWidth(150)
        self.guided_propose_rest_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.guided_configure_capacity_button.setMinimumWidth(150)
        self.guided_configure_capacity_button.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Fixed
        )

        self.guided_pallet_combo.setMinimumWidth(0)
        self.guided_pallet_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.guided_splitter.setMinimumWidth(0)
        self.guided_splitter.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    def configure_pallet_capacity(self) -> None:
        super().configure_pallet_capacity()
        if getattr(self, "_guided_ready", False):
            self._refresh_guided_ui()

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

    def _guided_delete_current_pallet(self) -> None:
        sequence = self._selected_sequence
        if sequence is None:
            self.issue_label.show_warning("Seleccione un pallet para eliminar.")
            return
        pallet = next(
            (item for item in self._pallets if int(item["sequence"]) == int(sequence)),
            None,
        )
        if pallet is None:
            return
        if int(sequence) in self._locked_sequences:
            self.issue_label.show_warning("Libere el pallet antes de eliminarlo.")
            return
        allocations = pallet.get("allocations") or []
        if allocations:
            answer = QMessageBox.question(
                self,
                "Eliminar pallet",
                (
                    f"El pallet {sequence} tiene mercaderia asignada.\n\n"
                    "Si lo elimina, esa mercaderia volvera a quedar pendiente."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        old_locked = set(self._locked_sequences)
        remaining = [item for item in self._pallets if int(item["sequence"]) != int(sequence)]
        remaining.sort(key=lambda item: int(item["sequence"]))
        sequence_map: dict[int, int] = {}
        for new_sequence, item in enumerate(remaining, start=1):
            old_sequence = int(item["sequence"])
            sequence_map[old_sequence] = new_sequence
            item["sequence"] = new_sequence

        self._pallets = remaining
        self._locked_sequences = {
            sequence_map[old_sequence]
            for old_sequence in old_locked
            if old_sequence in sequence_map
        }
        for item in self._pallets:
            item["locked"] = int(item["sequence"]) in self._locked_sequences

        if self._pallets:
            self._selected_sequence = min(int(sequence), len(self._pallets))
        else:
            self._selected_sequence = None
        self._refresh()
        self.composition_changed.emit()
        self.issue_label.show_success("Pallet eliminado. La numeracion fue reordenada.")

    def _rebuild_guided_pallet_selector(self) -> None:
        while self.guided_pallet_selector_grid.count():
            item = self.guided_pallet_selector_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._guided_pallet_buttons = {}

        for index, pallet in enumerate(sorted(self._pallets, key=lambda item: int(item["sequence"]))):
            sequence = int(pallet["sequence"])
            button = QPushButton(str(sequence))
            button.setObjectName(f"guidedPalletSelectorButton_{sequence}")
            button.setCheckable(True)
            selected = sequence == self._selected_sequence
            button.setChecked(selected)
            button.setMinimumWidth(36)
            button.setMaximumHeight(30)
            if selected:
                button.setStyleSheet(
                    "QPushButton { background: #173a59; color: white; font-weight: 900; "
                    "border: 2px solid #0f2e49; border-radius: 6px; }"
                )
            else:
                button.setStyleSheet("")
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
        # La pantalla se construye antes de que la base este disponible (#668).
        # Mismo criterio que `_refresh_auto_distribution_ui` del base: si no se
        # puede leer la capacidad, se muestra como no configurada.
        try:
            max_kg = PalletCapacityService.pallet_max_kg()
        except Exception:
            max_kg = None
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

        if self._selected_sequence is None:
            self.guided_current_pallet_label.setText("PALLET ACTUAL: -")
            self.guided_delete_pallet_button.setEnabled(False)
        else:
            self.guided_current_pallet_label.setText(
                f"PALLET ACTUAL: {self._selected_sequence}"
            )
            self.guided_delete_pallet_button.setEnabled(True)

        self.guided_partial_button.show()
        self._rebuild_guided_pallet_selector()


__all__ = [
    "PalletCard",
    "PalletCompositionWidget",
    "_kg_text",
    "_quantity_text",
]

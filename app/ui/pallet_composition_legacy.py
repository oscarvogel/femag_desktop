from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Product
from app.services.pallet_composition_service import (
    AllocationDraft,
    LooseAllocationDraft,
    PalletCompositionService,
    PalletDraft,
    RequestedLine,
)
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.form_feedback import FormFeedback


def _kg_text(value) -> str:
    decimal_value = Decimal(str(value)).quantize(Decimal("0.001"))
    whole, fraction = f"{decimal_value:.3f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    significant_fraction = fraction.rstrip("0")
    return f"{grouped}{',' + significant_fraction if significant_fraction else ''} kg"


def _quantity_text(value) -> str:
    decimal_value = Decimal(str(value))
    return format(decimal_value.normalize(), "f")


class PalletCard(QFrame):
    selected = pyqtSignal(int)

    def __init__(self, sequence: int, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.setObjectName(f"palletCard{sequence}")
        self.setCursor(Qt.PointingHandCursor)
        # Permitir que la card escale segun el ancho disponible para que la
        # composicion entre en pantallas chicas (notebooks 1280x720). Sigue
        # siendo cuadrada porque Qt respeta mismo ancho/alto cuando ambos
        # limites inferior y superior son iguales.
        self.setMinimumSize(150, 150)
        self.setMaximumSize(200, 200)
        size_policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        size_policy.setHeightForWidth(True)
        self.setSizePolicy(size_policy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.title_label = QLabel(f"PALLET {sequence}")
        self.title_label.setStyleSheet("font-weight: 800; font-size: 15px;")
        self.kg_label = QLabel("0 kg")
        self.kg_label.setAlignment(Qt.AlignCenter)
        self.kg_label.setStyleSheet("font-weight: 900; font-size: 27px;")
        self.article_count_label = QLabel("0 articulos")
        self.client_count_label = QLabel("0 clientes")
        self.status_label = QLabel("Incompleto")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.kg_label)
        layout.addStretch(1)
        layout.addWidget(self.article_count_label)
        layout.addWidget(self.client_count_label)
        layout.addWidget(self.status_label)
        self.set_state("incomplete")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.sequence)
        super().mousePressEvent(event)

    def set_state(self, state: str) -> None:
        self.setProperty("compositionState", state)
        colors = {
            "complete": ("#dff5ea", "#24755a", "Completo"),
            "incomplete": ("#fff3d5", "#d89614", "Incompleto"),
            "invalid": ("#fde6e6", "#b53b3b", "Revisar"),
        }
        background, border, label = colors[state]
        self.status_label.setText(label)
        self.setStyleSheet(
            f"QFrame#{self.objectName()} {{ background: {background}; border: 3px solid {border}; "
            "border-radius: 14px; } QLabel { border: none; background: transparent; }"
        )


class PalletCompositionWidget(QWidget):
    composition_changed = pyqtSignal()

    def __init__(self, *, destinations: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("palletCompositionWidget")
        self._destinations: list[dict] = destinations or []
        self._pallets: list[dict] = []
        self._loose: list[dict] = []
        self._cards: dict[int, PalletCard] = {}
        self._selected_sequence: int | None = None
        self._build()
        self._refresh_destination_combo()
        self._refresh()

    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Composicion de pallets")
        heading.setObjectName("palletCompositionTitle")
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        left_layout.addWidget(heading)

        total_frame = QFrame()
        total_frame.setObjectName("loadOrderKgTotalFrame")
        total_frame.setStyleSheet(
            "QFrame#loadOrderKgTotalFrame { background-color: #173a59; border: 0; border-radius: 12px; }"
        )
        total_layout = QVBoxLayout(total_frame)
        total_caption = QLabel("TOTAL DE LA ORDEN")
        total_caption.setAlignment(Qt.AlignCenter)
        total_caption.setStyleSheet("color: #ffffff; background: transparent; border: 0;")
        self.total_kg_label = QLabel("0 kg")
        self.total_kg_label.setObjectName("loadOrderTotalKg")
        self.total_kg_label.setAlignment(Qt.AlignCenter)
        self.total_kg_label.setStyleSheet(
            "font-size: 38px; font-weight: 900; color: #ffffff; background: transparent; border: 0;"
        )
        self.summary_label = QLabel("0 pallets · 0 completos · 0 pendientes")
        self.summary_label.setObjectName("loadOrderPalletSummary")
        self.summary_label.setAlignment(Qt.AlignCenter)
        self.summary_label.setStyleSheet("color: #ffffff; background: transparent; border: 0;")
        total_layout.addWidget(total_caption)
        total_layout.addWidget(self.total_kg_label)
        total_layout.addWidget(self.summary_label)
        left_layout.addWidget(total_frame)

        scroll = QScrollArea()
        scroll.setObjectName("palletCardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # Keep the card area bounded so the batch actions and dialog footer
        # remain visible on notebook-height windows. Extra pallet rows still
        # remain reachable through the scroll area.
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll.setMinimumHeight(0)
        scroll.setMaximumHeight(170)
        self.card_container = QWidget()
        self.card_grid = QGridLayout(self.card_container)
        self.card_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.card_grid.setSpacing(10)
        scroll.setWidget(self.card_container)
        left_layout.addWidget(scroll, 1)

        pallet_actions = QFrame()
        pallet_actions.setObjectName("palletBatchActions")
        pallet_actions_layout = QGridLayout(pallet_actions)
        pallet_actions_layout.setContentsMargins(0, 0, 0, 0)
        pallet_actions_layout.addWidget(QLabel("Cantidad de pallets a agregar"), 0, 0, 1, 2)
        self.bulk_pallet_count_input = QSpinBox()
        self.bulk_pallet_count_input.setObjectName("bulkPalletCountInput")
        self.bulk_pallet_count_input.setRange(0, 999)
        # Qt 5.15 trata setSpecialValueText("") como "sin special text" y
        # renderiza "0". Usamos un espacio para que el input se vea vacío
        # cuando el valor es 0, manteniendo la lógica de "no crear pallet".
        self.bulk_pallet_count_input.setSpecialValueText(" ")
        self.bulk_pallet_count_input.setValue(0)
        pallet_actions_layout.addWidget(self.bulk_pallet_count_input, 1, 0)
        self.add_pallet_button = QPushButton("Agregar primer pallet")
        self.add_pallet_button.setObjectName("addPalletCardButton")
        self.add_pallet_button.clicked.connect(self._add_pallets_from_editor)
        pallet_actions_layout.addWidget(self.add_pallet_button, 1, 1)
        self.clear_assignments_button = QPushButton("Quitar todas las asignaciones")
        self.clear_assignments_button.setObjectName("clearAllPalletAllocationsButton")
        self.clear_assignments_button.setProperty("secondary", True)
        self.clear_assignments_button.clicked.connect(self._confirm_clear_allocations)
        pallet_actions_layout.addWidget(self.clear_assignments_button, 2, 0, 1, 2)
        left_layout.addWidget(pallet_actions)

        self.issue_label = FormFeedback("palletCompositionIssues")
        left_layout.addWidget(self.issue_label)
        root.addWidget(left, 3)

        self.editor_panel = QFrame()
        self.editor_panel.setObjectName("palletEditorPanel")
        self.editor_panel.setMinimumWidth(240)
        self.editor_panel.installEventFilter(self)
        editor_panel_layout = QVBoxLayout(self.editor_panel)
        editor_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setObjectName("palletEditorScroll")
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_scroll.setMinimumSize(0, 0)
        self.editor_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        editor_content = QWidget()
        editor_content.setObjectName("palletEditorContent")
        editor_content.setMinimumSize(0, 0)
        editor_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        editor = QVBoxLayout(editor_content)
        editor.setContentsMargins(0, 0, 0, 0)
        self.editor_title = QLabel("Seleccione un pallet")
        self.editor_title.setStyleSheet("font-size: 17px; font-weight: 800;")
        editor.addWidget(self.editor_title)

        # Distribuir el contenido del editor en 3 tabs para que entre
        # en notebooks chicas. La tabla de asignaciones queda en su
        # propia tab en vez de estar siempre visible abajo.
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("palletEditorTabs")
        self.editor_tabs.setMinimumSize(0, 0)
        self.editor_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        tab_individual = QWidget()
        tab_individual.setObjectName("palletEditorTabIndividual")
        layout_individual = QVBoxLayout(tab_individual)
        layout_individual.setContentsMargins(0, 8, 0, 0)
        layout_individual.addWidget(QLabel("Cliente / destino"))
        self.destination_combo = QComboBox()
        self.destination_combo.setObjectName("palletDestinationInput")
        enable_combo_autocomplete(self.destination_combo, placeholder="Buscar destino...")
        self.destination_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.destination_combo.setMinimumContentsLength(1)
        self.destination_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.destination_combo.lineEdit().setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed
        )
        layout_individual.addWidget(self.destination_combo)
        layout_individual.addWidget(QLabel("Articulo"))
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("palletProductInput")
        enable_combo_autocomplete(self.product_combo, placeholder="Buscar producto...")
        layout_individual.addWidget(self.product_combo)
        layout_individual.addWidget(QLabel("Cantidad"))
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setObjectName("palletAllocationQuantityInput")
        self.quantity_input.setRange(0.001, 999999999)
        self.quantity_input.setDecimals(3)
        self.quantity_input.setValue(1)
        layout_individual.addWidget(self.quantity_input)
        self.add_allocation_button = QPushButton("Agregar mercaderia")
        self.add_allocation_button.setObjectName("addPalletAllocationButton")
        self.add_allocation_button.clicked.connect(self._add_from_editor)
        layout_individual.addWidget(self.add_allocation_button)
        self.add_loose_button = QPushButton("Marcar como suelto")
        self.add_loose_button.setObjectName("markLooseAllocationButton")
        self.add_loose_button.setProperty("secondary", True)
        self.add_loose_button.setToolTip(
            "Asigna la cantidad como mercaderia suelta, sin asociarla a ningun pallet."
        )
        self.add_loose_button.clicked.connect(self._add_loose_from_editor)
        layout_individual.addWidget(self.add_loose_button)
        layout_individual.addStretch(1)
        self.editor_tabs.addTab(tab_individual, "Individual")

        tab_masiva = QWidget()
        tab_masiva.setObjectName("palletEditorTabBulk")
        layout_masiva = QVBoxLayout(tab_masiva)
        layout_masiva.setContentsMargins(0, 8, 0, 0)
        bulk_assignment = QFrame()
        bulk_assignment.setObjectName("bulkPalletAssignmentPanel")
        bulk_layout = QGridLayout(bulk_assignment)
        bulk_layout.setContentsMargins(0, 8, 0, 8)
        bulk_title = QLabel("Asignacion en lote")
        bulk_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        bulk_layout.addWidget(bulk_title, 0, 0, 1, 2)
        bulk_layout.addWidget(QLabel("Desde pallet"), 1, 0)
        bulk_layout.addWidget(QLabel("Cantidad de pallets"), 1, 1)
        self.bulk_start_input = QSpinBox()
        self.bulk_start_input.setObjectName("bulkPalletStartInput")
        self.bulk_start_input.setRange(0, 0)
        self.bulk_target_count_input = QSpinBox()
        self.bulk_target_count_input.setObjectName("bulkPalletTargetCountInput")
        self.bulk_target_count_input.setRange(0, 0)
        bulk_layout.addWidget(self.bulk_start_input, 2, 0)
        bulk_layout.addWidget(self.bulk_target_count_input, 2, 1)
        bulk_layout.addWidget(QLabel("Cantidad por pallet"), 3, 0, 1, 2)
        self.bulk_quantity_input = QDoubleSpinBox()
        self.bulk_quantity_input.setObjectName("bulkPalletQuantityInput")
        self.bulk_quantity_input.setRange(0, 0)
        self.bulk_quantity_input.setDecimals(3)
        bulk_layout.addWidget(self.bulk_quantity_input, 4, 0, 1, 2)
        self.bulk_preview_label = FormFeedback("bulkPalletAssignmentPreview")
        self.bulk_preview_label.show_info("Agregue pallets para usar la asignacion en lote.")
        bulk_layout.addWidget(self.bulk_preview_label, 5, 0, 1, 2)
        self.bulk_assign_button = QPushButton("Asignar a pallets")
        self.bulk_assign_button.setObjectName("assignPalletsBatchButton")
        self.bulk_assign_button.clicked.connect(self._assign_bulk_from_editor)
        bulk_layout.addWidget(self.bulk_assign_button, 6, 0, 1, 2)
        layout_masiva.addWidget(bulk_assignment)
        layout_masiva.addStretch(1)
        self.editor_tabs.addTab(tab_masiva, "Masiva")

        tab_asignaciones = QWidget()
        tab_asignaciones.setObjectName("palletEditorTabAllocations")
        layout_asignaciones = QVBoxLayout(tab_asignaciones)
        layout_asignaciones.setContentsMargins(0, 8, 0, 0)
        self.allocation_table = QTableWidget(0, 5)
        self.allocation_table.setObjectName("palletAllocationTable")
        self.allocation_table.setHorizontalHeaderLabels(
            ("Cliente / destino", "Articulo", "Cantidad", "Kg", "Accion")
        )
        self.allocation_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.allocation_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.allocation_table.verticalHeader().setVisible(False)
        self.allocation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.allocation_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.allocation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout_asignaciones.addWidget(self.allocation_table, 1)
        self.editor_tabs.addTab(tab_asignaciones, "Asignaciones")

        tab_suelto = QWidget()
        tab_suelto.setObjectName("palletEditorTabLoose")
        layout_suelto = QVBoxLayout(tab_suelto)
        layout_suelto.setContentsMargins(0, 8, 0, 0)
        self.loose_table = QTableWidget(0, 5)
        self.loose_table.setObjectName("looseAllocationTable")
        self.loose_table.setHorizontalHeaderLabels(
            ("Cliente / destino", "Articulo", "Cantidad", "Kg", "Accion")
        )
        self.loose_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.loose_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.loose_table.verticalHeader().setVisible(False)
        self.loose_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.loose_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.loose_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout_suelto.addWidget(self.loose_table, 1)
        self.editor_tabs.addTab(tab_suelto, "Suelto")

        editor.addWidget(self.editor_tabs, 1)
        self.editor_scroll.setWidget(editor_content)
        editor_panel_layout.addWidget(self.editor_scroll)
        self.destination_combo.currentIndexChanged.connect(self._refresh_product_combo)
        self.destination_combo.currentIndexChanged.connect(
            self._sync_destination_tooltip
        )
        self.product_combo.currentIndexChanged.connect(self._suggest_remaining_quantity)
        self.quantity_input.valueChanged.connect(self._update_editor_actions)
        self.bulk_start_input.valueChanged.connect(self._bulk_start_changed)
        self.bulk_target_count_input.valueChanged.connect(self._suggest_bulk_quantity)
        self.bulk_quantity_input.valueChanged.connect(self._update_editor_actions)
        root.addWidget(self.editor_panel, 2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_destination_combo_to_editor()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.editor_panel and event.type() == QEvent.Resize:
            self._fit_destination_combo_to_editor(event.size().width())
        return super().eventFilter(watched, event)

    def _fit_destination_combo_to_editor(self, panel_width: int | None = None) -> None:
        if not hasattr(self, "editor_scroll") or not hasattr(self, "destination_combo"):
            return
        available_width = max((panel_width or self.editor_panel.width()) - 4, 120)
        self.destination_combo.setMaximumWidth(available_width)

    def set_destinations(self, destinations: list[dict]) -> None:
        self._destinations = destinations
        valid_keys = {
            (destination["address_id"], product["product_id"])
            for destination in destinations
            for product in destination.get("products") or []
        }
        for pallet in self._pallets:
            pallet["allocations"] = [
                allocation
                for allocation in pallet["allocations"]
                if (allocation["address_id"], allocation["product_id"]) in valid_keys
            ]
        self._loose = [
            allocation
            for allocation in self._loose
            if (allocation["address_id"], allocation["product_id"]) in valid_keys
        ]
        self._refresh_destination_combo()
        self._refresh()

    def add_pallet(self) -> int:
        return self.add_pallets(1)[0]

    def add_pallets(self, count: int) -> list[int]:
        count = int(count)
        if count <= 0:
            raise ValueError("La cantidad de pallets a agregar debe ser mayor a cero.")
        first_sequence = max((pallet["sequence"] for pallet in self._pallets), default=0) + 1
        sequences = list(range(first_sequence, first_sequence + count))
        self._pallets.extend(
            {"sequence": sequence, "pallet_type_id": None, "allocations": []}
            for sequence in sequences
        )
        self._selected_sequence = first_sequence
        self._refresh()
        self.composition_changed.emit()
        return sequences

    def _add_pallets_from_editor(self) -> None:
        count = self.bulk_pallet_count_input.value()
        if count <= 0:
            self.bulk_pallet_count_input.setFocus()
            return
        self.add_pallets(count)
        self.bulk_pallet_count_input.setValue(0)
        self.bulk_pallet_count_input.setFocus()
        self.bulk_pallet_count_input.selectAll()

    def add_allocation(self, sequence: int, address_id: int, product_id: int, quantity) -> None:
        destination = self._destination(address_id)
        product_draft = next(
            product for product in destination.get("products") or [] if product["product_id"] == product_id
        )
        product = Product.get_by_id(product_id)
        self._add_allocation_to_pallet(
            self._pallet(sequence),
            destination,
            product_draft,
            product,
            quantity,
        )
        self._selected_sequence = sequence
        self._refresh()
        self.composition_changed.emit()

    def add_allocations_bulk(
        self,
        sequences: list[int],
        address_id: int,
        product_id: int,
        quantity_per_pallet,
    ) -> None:
        if not sequences:
            raise ValueError("Seleccione al menos un pallet para la asignacion en lote.")
        if len(set(sequences)) != len(sequences):
            raise ValueError("Los pallets de la asignacion en lote no pueden repetirse.")
        quantity = Decimal(str(quantity_per_pallet))
        if quantity <= 0:
            raise ValueError("La cantidad por pallet debe ser mayor a cero.")
        existing_sequences = {pallet["sequence"] for pallet in self._pallets}
        if any(sequence not in existing_sequences for sequence in sequences):
            raise ValueError("La asignacion en lote incluye pallets inexistentes.")
        total = quantity * len(sequences)
        if total > self._remaining_quantity(address_id, product_id):
            raise ValueError("La asignacion en lote supera la cantidad pendiente.")
        destination = self._destination(address_id)
        product_draft = next(
            product for product in destination.get("products") or [] if product["product_id"] == product_id
        )
        product = Product.get_by_id(product_id)
        for sequence in sequences:
            self._add_allocation_to_pallet(
                self._pallet(sequence),
                destination,
                product_draft,
                product,
                quantity,
            )
        self._selected_sequence = sequences[0]
        self._refresh()
        self.composition_changed.emit()

    def _add_allocation_to_pallet(
        self,
        pallet: dict,
        destination: dict,
        product_draft: dict,
        product: Product,
        quantity,
    ) -> None:
        address_id = destination["address_id"]
        product_id = product.id
        existing = next(
            (
                allocation
                for allocation in pallet["allocations"]
                if allocation["address_id"] == address_id and allocation["product_id"] == product_id
            ),
            None,
        )
        if existing is not None:
            existing["quantity"] = float(existing["quantity"]) + float(quantity)
        else:
            pallet["allocations"].append(
                {
                    "client_id": destination["client_id"],
                    "address_id": address_id,
                    "product_id": product_id,
                    "product_label": product_draft["product_label"],
                    "quantity": float(quantity),
                    "peso_unitario_kg": Decimal(product.peso_unitario_kg),
                }
            )

    def add_loose_allocation(self, address_id: int, product_id: int, quantity) -> None:
        destination = self._destination(address_id)
        product_draft = next(
            product for product in destination.get("products") or [] if product["product_id"] == product_id
        )
        product = Product.get_by_id(product_id)
        self._add_loose_allocation(
            destination,
            product_draft,
            product,
            quantity,
        )
        self._refresh()
        self.composition_changed.emit()

    def _add_loose_allocation(
        self,
        destination: dict,
        product_draft: dict,
        product: Product,
        quantity,
    ) -> None:
        address_id = destination["address_id"]
        product_id = product.id
        existing = next(
            (
                allocation
                for allocation in self._loose
                if allocation["address_id"] == address_id and allocation["product_id"] == product_id
            ),
            None,
        )
        if existing is not None:
            existing["quantity"] = float(existing["quantity"]) + float(quantity)
        else:
            self._loose.append(
                {
                    "client_id": destination["client_id"],
                    "address_id": address_id,
                    "product_id": product_id,
                    "product_label": product_draft["product_label"],
                    "quantity": float(quantity),
                    "peso_unitario_kg": Decimal(product.peso_unitario_kg),
                }
            )

    def remove_loose_allocation(self, index: int) -> None:
        if 0 <= index < len(self._loose):
            self._loose.pop(index)
            self._refresh()
            self.composition_changed.emit()

    def clear_all_allocations(self) -> int:
        allocation_count = sum(len(pallet["allocations"]) for pallet in self._pallets)
        if not allocation_count:
            return 0
        for pallet in self._pallets:
            pallet["allocations"] = []
        self._refresh()
        self.composition_changed.emit()
        return allocation_count

    def _confirm_clear_allocations(self) -> None:
        allocation_count = sum(len(pallet["allocations"]) for pallet in self._pallets)
        if not allocation_count:
            return
        answer = QMessageBox.question(
            self,
            "Quitar todas las asignaciones",
            (
                f"Se quitaran {allocation_count} asignaciones de mercaderia.\n\n"
                "Las tarjetas y su numeracion se conservaran. "
                "El cambio se aplicara al guardar los pallets."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.clear_all_allocations()

    def load_pallets(self, pallets: list[dict], *, loose: list[dict] | None = None) -> None:
        self._pallets = []
        for pallet in pallets:
            self._pallets.append(
                {
                    "sequence": pallet["sequence"],
                    "pallet_type_id": pallet.get("pallet_type_id"),
                    "allocations": [dict(allocation) for allocation in pallet.get("allocations") or []],
                }
            )
        self._loose = [dict(allocation) for allocation in loose or []]
        self._selected_sequence = self._pallets[0]["sequence"] if self._pallets else None
        self._refresh()

    def pallet_drafts(self) -> list[dict]:
        return [
            {
                "sequence": pallet["sequence"],
                "pallet_type_id": pallet.get("pallet_type_id"),
                "allocations": [dict(allocation) for allocation in pallet["allocations"]],
            }
            for pallet in self._pallets
        ]

    def loose_drafts(self) -> list[dict]:
        return [dict(allocation) for allocation in self._loose]

    def card_for_sequence(self, sequence: int) -> PalletCard:
        return self._cards[sequence]

    def _pallet(self, sequence: int) -> dict:
        return next(pallet for pallet in self._pallets if pallet["sequence"] == sequence)

    def _destination(self, address_id: int) -> dict:
        return next(destination for destination in self._destinations if destination["address_id"] == address_id)

    def _requested_lines(self) -> list[RequestedLine]:
        return [
            RequestedLine(
                destination_id=destination["address_id"],
                product_id=product["product_id"],
                quantity=product["quantity"],
                label=f"{destination['client_label']} / {destination['address_label']} / {product['product_label']}",
            )
            for destination in self._destinations
            for product in destination.get("products") or []
        ]

    def _domain_pallets(self) -> list[PalletDraft]:
        return [
            PalletDraft(
                sequence=pallet["sequence"],
                allocations=tuple(
                    AllocationDraft(
                        destination_id=allocation["address_id"],
                        product_id=allocation["product_id"],
                        quantity=allocation["quantity"],
                        peso_unitario_kg=allocation["peso_unitario_kg"],
                        label=allocation.get("product_label", ""),
                        client_id=allocation.get("client_id"),
                    )
                    for allocation in pallet["allocations"]
                ),
            )
            for pallet in self._pallets
        ]

    def _domain_loose(self) -> list[LooseAllocationDraft]:
        return [
            LooseAllocationDraft(
                destination_id=allocation["address_id"],
                product_id=allocation["product_id"],
                quantity=allocation["quantity"],
                peso_unitario_kg=allocation["peso_unitario_kg"],
                label=allocation.get("product_label", ""),
                client_id=allocation.get("client_id"),
            )
            for allocation in self._loose
        ]

    def _refresh(self) -> None:
        result = PalletCompositionService().reconcile(
            requested=self._requested_lines(),
            pallets=self._domain_pallets(),
            loose=self._domain_loose(),
        )
        self.total_kg_label.setText(_kg_text(result.total_kg))
        pending_keys = {
            (issue.destination_id, issue.product_id)
            for issue in result.issues
            if issue.code == "pending"
        }
        states = {}
        requested_by_key = {
            (line.destination_id, line.product_id): line.quantity
            for line in self._requested_lines()
        }
        assigned_by_key = {key: Decimal("0.000") for key in requested_by_key}
        pallet_keys = {}
        for pallet in sorted(self._pallets, key=lambda item: item["sequence"]):
            keys = {(item["address_id"], item["product_id"]) for item in pallet["allocations"]}
            pallet_keys[pallet["sequence"]] = keys
            state = "incomplete" if not keys else "complete"
            for allocation in pallet["allocations"]:
                key = (allocation["address_id"], allocation["product_id"])
                assigned_by_key[key] = assigned_by_key.get(key, Decimal("0.000")) + Decimal(
                    str(allocation["quantity"])
                )
                if assigned_by_key[key] > requested_by_key.get(key, Decimal("0.000")):
                    state = "invalid"
                elif allocation["peso_unitario_kg"] <= 0 and state != "invalid":
                    state = "incomplete"
            states[pallet["sequence"]] = state
        for sequence, keys in pallet_keys.items():
            if states[sequence] == "complete" and keys & pending_keys:
                states[sequence] = "incomplete"
        complete_count = sum(state == "complete" for state in states.values())
        pending_count = len(self._pallets) - complete_count
        if not self._pallets:
            self.summary_label.setText(f"{_quantity_text(result.pending_quantity)} unidades pendientes")
        else:
            self.summary_label.setText(
                f"{len(self._pallets)} pallets · {complete_count} "
                f"{'completo' if complete_count == 1 else 'completos'} · {pending_count} "
                f"{'pendiente' if pending_count == 1 else 'pendientes'}"
            )
        issue_message = "\n".join(
            issue.message for issue in result.issues if issue.code != "no_pallets"
        )
        if issue_message:
            self.issue_label.show_warning(issue_message)
        else:
            self.issue_label.clear_message()
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = {}
        result_by_sequence = {pallet.sequence: pallet for pallet in result.pallets}
        if not self._pallets:
            empty_state = QLabel(
                "Todavia no agregaste pallets.\n"
                f"Hay {_quantity_text(result.pending_quantity)} unidades pendientes de asignar."
            )
            empty_state.setObjectName("palletCompositionEmptyState")
            empty_state.setAlignment(Qt.AlignCenter)
            empty_state.setWordWrap(True)
            empty_state.setMinimumSize(520, 180)
            empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            empty_state.setStyleSheet(
                "color: #526174; font-size: 16px; font-weight: 600; padding: 40px; "
                "background: transparent; border: 0;"
            )
            self.card_grid.addWidget(empty_state, 0, 0, 1, 3)
        for index, pallet in enumerate(self._pallets):
            card = PalletCard(pallet["sequence"])
            pallet_result = result_by_sequence[pallet["sequence"]]
            card.kg_label.setText(_kg_text(pallet_result.total_kg))
            card.article_count_label.setText(
                f"{pallet_result.allocation_count} articulo" + ("s" if pallet_result.allocation_count != 1 else "")
            )
            card.client_count_label.setText(
                f"{pallet_result.client_count} cliente" + ("s" if pallet_result.client_count != 1 else "")
            )
            card.set_state(states[pallet["sequence"]])
            card.selected.connect(self._select_pallet)
            self.card_grid.addWidget(card, index // 3, index % 3)
            self._cards[pallet["sequence"]] = card
        self.add_pallet_button.setText("+ Agregar pallet" if self._pallets else "Agregar primer pallet")
        self.clear_assignments_button.setEnabled(
            any(pallet["allocations"] for pallet in self._pallets)
        )
        self._update_bulk_ranges()
        self._render_editor()

    def _select_pallet(self, sequence: int) -> None:
        self._selected_sequence = sequence
        self.bulk_start_input.setValue(sequence)
        self._render_editor()

    def _update_bulk_ranges(self) -> None:
        sequences = sorted(pallet["sequence"] for pallet in self._pallets)
        if not sequences:
            self.bulk_start_input.setRange(0, 0)
            self.bulk_target_count_input.setRange(0, 0)
            self.bulk_start_input.setEnabled(False)
            self.bulk_target_count_input.setEnabled(False)
            self.bulk_quantity_input.setEnabled(False)
            return
        self.bulk_start_input.setEnabled(True)
        self.bulk_target_count_input.setEnabled(True)
        self.bulk_quantity_input.setEnabled(True)
        self.bulk_start_input.setRange(sequences[0], sequences[-1])
        if self.bulk_start_input.value() not in sequences:
            self.bulk_start_input.setValue(self._selected_sequence or sequences[0])
        self._bulk_start_changed()

    def _bulk_start_changed(self) -> None:
        if not self._pallets:
            return
        start = self.bulk_start_input.value()
        sequences = {pallet["sequence"] for pallet in self._pallets}
        available = 0
        while start + available in sequences:
            available += 1
        if available <= 0:
            self.bulk_target_count_input.setRange(0, 0)
            self._update_editor_actions()
            return
        previous = max(self.bulk_target_count_input.value(), 1)
        self.bulk_target_count_input.setRange(1, available)
        self.bulk_target_count_input.setValue(min(previous, available))
        self._suggest_bulk_quantity()

    def _refresh_destination_combo(self) -> None:
        selected = self.destination_combo.currentData() if hasattr(self, "destination_combo") else None
        self.destination_combo.clear()
        self.destination_combo.addItem("", None)
        for destination in self._destinations:
            self.destination_combo.addItem(
                f"{destination['client_label']} · {destination['address_label']}",
                destination["address_id"],
            )
        index = self.destination_combo.findData(selected)
        if index >= 0:
            self.destination_combo.setCurrentIndex(index)
        self._sync_destination_tooltip()
        self._refresh_product_combo()

    def _sync_destination_tooltip(self) -> None:
        index = self.destination_combo.currentIndex()
        full_label = self.destination_combo.itemText(index) if index >= 0 else ""
        self.destination_combo.setToolTip(full_label)
        line_edit = self.destination_combo.lineEdit()
        if line_edit is not None:
            line_edit.setToolTip(
                full_label or "Clic para ver la lista, escribí para filtrar"
            )

    def _refresh_product_combo(self) -> None:
        address_id = self.destination_combo.currentData()
        self.product_combo.clear()
        self.product_combo.addItem("", None)
        if address_id is None:
            self._update_editor_actions()
            return
        destination = self._destination(address_id)
        for product in destination.get("products") or []:
            self.product_combo.addItem(product["product_label"], product["product_id"])
        self._suggest_remaining_quantity()

    def _remaining_quantity(self, address_id: int, product_id: int) -> Decimal:
        destination = self._destination(address_id)
        requested = Decimal(
            str(
                next(
                    product["quantity"]
                    for product in destination.get("products") or []
                    if product["product_id"] == product_id
                )
            )
        )
        assigned = sum(
            (
                Decimal(str(allocation["quantity"]))
                for pallet in self._pallets
                for allocation in pallet["allocations"]
                if allocation["address_id"] == address_id and allocation["product_id"] == product_id
            ),
            Decimal("0"),
        )
        assigned += sum(
            (
                Decimal(str(allocation["quantity"]))
                for allocation in self._loose
                if allocation["address_id"] == address_id and allocation["product_id"] == product_id
            ),
            Decimal("0"),
        )
        return max(requested - assigned, Decimal("0"))

    def _suggest_remaining_quantity(self) -> None:
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        if address_id is None or product_id is None:
            self.quantity_input.setRange(0.001, 999999999)
            self._update_editor_actions()
            return
        remaining = self._remaining_quantity(address_id, product_id)
        if remaining > 0:
            self.quantity_input.setRange(0.001, float(remaining))
        else:
            self.quantity_input.setRange(0, 0)
        self.quantity_input.setValue(float(remaining))
        self._suggest_bulk_quantity()
        self._update_editor_actions()

    def _suggest_bulk_quantity(self) -> None:
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        target_count = self.bulk_target_count_input.value()
        if address_id is None or product_id is None or target_count <= 0:
            self.bulk_quantity_input.setRange(0, 0)
            self._update_editor_actions()
            return
        remaining = self._remaining_quantity(address_id, product_id)
        if remaining <= 0:
            self.bulk_quantity_input.setRange(0, 0)
        else:
            suggested = (remaining / target_count).quantize(
                Decimal("0.001"),
                rounding=ROUND_DOWN,
            )
            self.bulk_quantity_input.setRange(0.001, float(remaining))
            self.bulk_quantity_input.setValue(float(suggested))
        self._update_editor_actions()

    def _add_from_editor(self) -> None:
        if self._selected_sequence is None:
            return
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        if address_id is None or product_id is None:
            return
        quantity = Decimal(str(self.quantity_input.value()))
        if quantity <= 0 or quantity > self._remaining_quantity(address_id, product_id):
            return
        self.add_allocation(self._selected_sequence, address_id, product_id, quantity)

    def _add_loose_from_editor(self) -> None:
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        if address_id is None or product_id is None:
            return
        quantity = Decimal(str(self.quantity_input.value()))
        if quantity <= 0 or quantity > self._remaining_quantity(address_id, product_id):
            return
        self.add_loose_allocation(address_id, product_id, quantity)

    def _assign_bulk_from_editor(self) -> None:
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        if address_id is None or product_id is None:
            return
        start = self.bulk_start_input.value()
        count = self.bulk_target_count_input.value()
        sequences = list(range(start, start + count))
        try:
            self.add_allocations_bulk(
                sequences,
                address_id,
                product_id,
                Decimal(str(self.bulk_quantity_input.value())),
            )
        except ValueError as exc:
            self.bulk_preview_label.show_error(str(exc))

    def _remove_allocation(self, row: int) -> None:
        if self._selected_sequence is None:
            return
        pallet = self._pallet(self._selected_sequence)
        if 0 <= row < len(pallet["allocations"]):
            pallet["allocations"].pop(row)
            self._refresh()
            self.composition_changed.emit()

    def _remove_loose_row(self, row: int) -> None:
        self.remove_loose_allocation(row)

    def _render_loose_table(self) -> None:
        selected_row = self.loose_table.currentRow()
        self.loose_table.setRowCount(len(self._loose))
        for row, allocation in enumerate(self._loose):
            destination = self._destination(allocation["address_id"])
            kilos = Decimal(str(allocation["quantity"])) * Decimal(str(allocation["peso_unitario_kg"]))
            values = (
                f"{destination['client_label']} · {destination['address_label']}",
                allocation.get("product_label", str(allocation["product_id"])),
                f"{allocation['quantity']:g}",
                _kg_text(kilos),
            )
            for column, value in enumerate(values):
                self.loose_table.setItem(row, column, QTableWidgetItem(value))
            remove_button = QPushButton("Quitar")
            remove_button.setObjectName(f"removeLooseAllocationButton_{row}")
            remove_button.setToolTip("Quitar esta asignacion suelta")
            remove_button.clicked.connect(
                lambda _checked=False, loose_row=row: self._remove_loose_row(loose_row)
            )
            self.loose_table.setCellWidget(row, 4, remove_button)
        if self._loose:
            self.loose_table.selectRow(min(max(selected_row, 0), len(self._loose) - 1))

    def _render_editor(self) -> None:
        self._render_loose_table()
        if self._selected_sequence is None:
            self.editor_title.setText("Marcar mercaderia como suelta o agregar un pallet")
            self.allocation_table.setRowCount(0)
            self.allocation_table.setEnabled(False)
            for control in (
                self.destination_combo,
                self.product_combo,
                self.quantity_input,
            ):
                control.setEnabled(True)
            self._suggest_remaining_quantity()
            self._update_editor_actions()
            return
        pallet = self._pallet(self._selected_sequence)
        self.editor_title.setText(f"PALLET {self._selected_sequence}")
        for control in (
            self.destination_combo,
            self.product_combo,
            self.quantity_input,
            self.allocation_table,
        ):
            control.setEnabled(True)
        selected_row = self.allocation_table.currentRow()
        self.allocation_table.setRowCount(len(pallet["allocations"]))
        for row, allocation in enumerate(pallet["allocations"]):
            destination = self._destination(allocation["address_id"])
            kilos = Decimal(str(allocation["quantity"])) * Decimal(str(allocation["peso_unitario_kg"]))
            values = (
                f"{destination['client_label']} · {destination['address_label']}",
                allocation.get("product_label", str(allocation["product_id"])),
                f"{allocation['quantity']:g}",
                _kg_text(kilos),
            )
            for column, value in enumerate(values):
                self.allocation_table.setItem(row, column, QTableWidgetItem(value))
            remove_button = QPushButton("Quitar")
            remove_button.setObjectName(f"removePalletProductButton_{row}")
            remove_button.setToolTip("Quitar este producto del pallet")
            remove_button.clicked.connect(
                lambda _checked=False, allocation_row=row: self._remove_allocation(allocation_row)
            )
            self.allocation_table.setCellWidget(row, 4, remove_button)
        if pallet["allocations"]:
            self.allocation_table.selectRow(min(max(selected_row, 0), len(pallet["allocations"]) - 1))
        self._suggest_remaining_quantity()

    def _update_editor_actions(self) -> None:
        has_pallet = self._selected_sequence is not None
        has_selection = (
            self.destination_combo.currentData() is not None and self.product_combo.currentData() is not None
        )
        can_add = (
            has_pallet
            and has_selection
            and self.quantity_input.value() > 0
        )
        self.add_allocation_button.setEnabled(can_add)
        self.add_loose_button.setEnabled(
            has_selection
            and self.quantity_input.value() > 0
        )
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        target_count = self.bulk_target_count_input.value()
        bulk_quantity = Decimal(str(self.bulk_quantity_input.value()))
        remaining = (
            self._remaining_quantity(address_id, product_id)
            if address_id is not None and product_id is not None
            else Decimal("0")
        )
        bulk_total = bulk_quantity * target_count
        has_targets = bool(self._pallets) and target_count > 0
        can_assign_bulk = (
            has_targets
            and address_id is not None
            and product_id is not None
            and bulk_quantity > 0
            and bulk_total <= remaining
        )
        self.bulk_assign_button.setEnabled(can_assign_bulk)
        if address_id is None or product_id is None:
            self.bulk_preview_label.show_info("Seleccione cliente/destino y articulo.")
        elif not has_targets:
            self.bulk_preview_label.show_info(
                "Agregue pallets para usar la asignacion en lote."
            )
        elif bulk_quantity <= 0:
            self.bulk_preview_label.show_info("Ingrese una cantidad por pallet.")
        elif bulk_total > remaining:
            self.bulk_preview_label.show_warning(
                f"La asignacion suma {_quantity_text(bulk_total)} unidades y supera "
                f"las {_quantity_text(remaining)} pendientes."
            )
        else:
            self.bulk_preview_label.show_info(
                f"{target_count} pallets x {_quantity_text(bulk_quantity)} = "
                f"{_quantity_text(bulk_total)} unidades. "
                f"Pendiente despues: {_quantity_text(remaining - bulk_total)}."
            )

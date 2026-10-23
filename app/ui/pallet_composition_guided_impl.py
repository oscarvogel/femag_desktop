from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_DOWN

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Product
from app.services.pallet_capacity_service import PalletCapacityService
from app.services.pallet_preparation_planner import PalletPreparationPlanner
from app.ui.pallet_composition_base import PalletCompositionWidget as _BasePalletCompositionWidget
from app.ui.pallet_composition_legacy import _kg_text, _quantity_text


class PalletCompositionWidget(_BasePalletCompositionWidget):
    """Workbench guiado de pallets inspirado en el flujo operativo de RND.

    La interfaz principal trabaja con mercaderia pendiente a la izquierda y el
    pallet actual a la derecha. El editor anterior se conserva como opcion
    avanzada y el guardado sigue usando los mismos drafts del circuito actual.
    """

    def __init__(self, *, destinations: list[dict] | None = None, parent=None):
        self._guided_ready = False
        super().__init__(destinations=destinations, parent=parent)
        self._install_guided_workbench()
        self._guided_ready = True
        self._refresh_guided_ui()

    def _refresh(self) -> None:
        super()._refresh()
        if getattr(self, "_guided_ready", False):
            self._refresh_guided_ui()

    def _current_rows(self) -> list[dict]:
        rows = super()._current_rows()
        weights = self._product_weights()
        metadata = []
        for destination in self._destinations:
            for product in destination.get("products") or []:
                product_id = int(product["product_id"])
                metadata.append(
                    {
                        "client_id": int(destination["client_id"]),
                        "address_id": int(destination["address_id"]),
                        "product_id": product_id,
                        "unit_kg": weights.get(product_id, Decimal("0")),
                    }
                )
        for row, extra in zip(rows, metadata):
            row.update(extra)
        return rows

    def _render_pending_table(self) -> None:
        super()._render_pending_table()
        needle = (
            self.pending_filter_input.text().strip().casefold()
            if hasattr(self, "pending_filter_input")
            else ""
        )
        visible_rows = []
        for row in self._current_rows():
            if row["pending"] <= 0:
                continue
            haystack = " ".join(
                (str(row["client"]), str(row["destination"]), str(row["product"]))
            ).casefold()
            if needle and needle not in haystack:
                continue
            visible_rows.append(row)
        for index, row in enumerate(visible_rows):
            item = self.pending_table.item(index, 0)
            if item is not None:
                item.setData(Qt.UserRole, row)

    def _install_guided_workbench(self) -> None:
        root = self.layout()
        legacy_left = self.total_kg_label.parentWidget().parentWidget()
        legacy_left.hide()
        self.editor_panel.hide()

        self.guided_splitter = QSplitter(Qt.Horizontal, self)
        self.guided_splitter.setObjectName("palletGuidedWorkbench")

        pending_group = QGroupBox("Mercaderia pendiente de preparar", self.guided_splitter)
        pending_group.setObjectName("palletGuidedPendingGroup")
        pending_layout = QVBoxLayout(pending_group)
        pending_help = QLabel(
            "Seleccione una o mas lineas. Puede agregarlas al pallet actual, "
            "cargar una cantidad parcial o distribuir una linea automaticamente."
        )
        pending_help.setWordWrap(True)
        pending_layout.addWidget(pending_help)

        self.pending_filter_input.setParent(pending_group)
        self.pending_table.setParent(pending_group)
        self.pending_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pending_table.cellDoubleClicked.connect(self._guided_pending_double_click)
        pending_layout.addWidget(self.pending_filter_input)
        pending_layout.addWidget(self.pending_table, 1)

        pending_actions = QHBoxLayout()
        self.guided_add_button = QPushButton("Agregar seleccion al pallet →")
        self.guided_add_button.setObjectName("guidedAddSelectionToPalletButton")
        self.guided_add_button.setProperty("role", "primary")
        self.guided_add_button.clicked.connect(self.add_selected_to_current_pallet)
        pending_actions.addWidget(self.guided_add_button, 2)

        self.guided_partial_button = QPushButton("Agregar parcial...")
        self.guided_partial_button.setObjectName("guidedAddPartialToPalletButton")
        self.guided_partial_button.clicked.connect(self.add_selected_partial)
        pending_actions.addWidget(self.guided_partial_button)

        # #767: la mercaderia suelta viaja en el camion sin ir en ningun pallet.
        # Antes solo se podia marcar desde el editor legacy, que el workbench
        # guiado deja oculto: la operatoria no tenia ninguna via.
        self.guided_loose_button = QPushButton("Marcar como suelta")
        self.guided_loose_button.setObjectName("guidedMarkLooseSelectionButton")
        self.guided_loose_button.setToolTip(
            "Marca la mercadería seleccionada como suelta: viaja en el camión sin ir en ningún pallet."
        )
        self.guided_loose_button.clicked.connect(self.mark_selected_as_loose)
        pending_actions.addWidget(self.guided_loose_button, 2)
        pending_layout.addLayout(pending_actions)

        # El reparto automatico va en su propia fila: sumar un quinto boton a
        # la fila de arriba apila los textos en la pantalla del cliente
        # (1638x969).
        pending_auto_actions = QHBoxLayout()
        self.guided_auto_button = QPushButton("Distribuir automaticamente")
        self.guided_auto_button.setObjectName("guidedAutoDistributeSelectedButton")
        self.guided_auto_button.clicked.connect(self.distribute_selected_automatically)
        pending_auto_actions.addWidget(self.guided_auto_button, 2)
        pending_layout.addLayout(pending_auto_actions)

        self.guided_propose_rest_button = QPushButton("Proponer resto")
        self.guided_propose_rest_button.setObjectName("guidedProposeRemainderButton")
        self.guided_propose_rest_button.setToolTip(
            "Rearma lo no fijado y conserva los pallets marcados como fijados."
        )
        self.guided_propose_rest_button.clicked.connect(self.propose_remainder)
        pending_layout.addWidget(self.guided_propose_rest_button)

        # #767: la mercaderia suelta de la carga se lista aca. El panel queda
        # abajo a proposito: si aparece entre la grilla y los botones, el
        # boton que el operador acaba de apretar se le mueve de debajo del
        # mouse. En estado vacio no ocupa espacio.
        self.guided_loose_group = QGroupBox("Mercadería suelta", pending_group)
        self.guided_loose_group.setObjectName("guidedLooseGoodsGroup")
        guided_loose_layout = QVBoxLayout(self.guided_loose_group)
        guided_loose_layout.setContentsMargins(4, 4, 4, 4)
        guided_loose_layout.setSpacing(4)
        self.guided_loose_table = QTableWidget(0, 5)
        self.guided_loose_table.setObjectName("guidedLooseGoodsTable")
        self.guided_loose_table.setHorizontalHeaderLabels(
            ("Cliente / destino", "Articulo", "Cantidad", "Kg", "Accion")
        )
        self.guided_loose_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.guided_loose_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents
        )
        self.guided_loose_table.verticalHeader().setVisible(False)
        self.guided_loose_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.guided_loose_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.guided_loose_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        guided_loose_layout.addWidget(self.guided_loose_table, 1)
        pending_layout.addWidget(self.guided_loose_group)
        self.guided_loose_group.hide()

        current_group = QGroupBox("Pallet actual", self.guided_splitter)
        current_group.setObjectName("palletGuidedCurrentGroup")
        current_layout = QVBoxLayout(current_group)
        pallet_row = QHBoxLayout()
        pallet_row.addWidget(QLabel("Pallet:"))
        self.guided_pallet_combo = QComboBox()
        self.guided_pallet_combo.setObjectName("guidedPalletCombo")
        self.guided_pallet_combo.currentIndexChanged.connect(self._guided_combo_changed)
        pallet_row.addWidget(self.guided_pallet_combo, 1)
        self.guided_new_pallet_button = QPushButton("Nuevo pallet")
        self.guided_new_pallet_button.setObjectName("guidedNewPalletButton")
        self.guided_new_pallet_button.clicked.connect(self._guided_new_pallet)
        pallet_row.addWidget(self.guided_new_pallet_button)
        current_layout.addLayout(pallet_row)

        self.guided_content_table = QTableWidget(0, 4)
        self.guided_content_table.setObjectName("guidedPalletContentTable")
        self.guided_content_table.setHorizontalHeaderLabels(
            ("Articulo", "Cliente / destino", "Cantidad", "Kg")
        )
        self.guided_content_table.horizontalHeader().setStretchLastSection(True)
        self.guided_content_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.guided_content_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.guided_content_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.guided_content_table.cellDoubleClicked.connect(self._guided_content_double_click)
        current_layout.addWidget(self.guided_content_table, 1)

        self.guided_totals_label = QLabel("Pallet vacio")
        self.guided_totals_label.setObjectName("guidedPalletTotalsLabel")
        self.guided_totals_label.setWordWrap(True)
        current_layout.addWidget(self.guided_totals_label)

        pallet_actions = QHBoxLayout()
        self.guided_remove_button = QPushButton("← Quitar del pallet")
        self.guided_remove_button.setObjectName("guidedRemoveFromPalletButton")
        self.guided_remove_button.clicked.connect(self.remove_selected_from_current_pallet)
        pallet_actions.addWidget(self.guided_remove_button)
        self.guided_lock_button = QPushButton("Fijar pallet")
        self.guided_lock_button.setObjectName("guidedTogglePalletLockButton")
        self.guided_lock_button.clicked.connect(self.toggle_selected_pallet_lock)
        pallet_actions.addWidget(self.guided_lock_button)
        current_layout.addLayout(pallet_actions)

        self.guided_splitter.addWidget(pending_group)
        self.guided_splitter.addWidget(current_group)
        self.guided_splitter.setStretchFactor(0, 3)
        self.guided_splitter.setStretchFactor(1, 2)
        root.addWidget(self.guided_splitter, 1)

    def _selected_pending_rows(self) -> list[dict]:
        selected = sorted({index.row() for index in self.pending_table.selectedIndexes()})
        rows = []
        for row_index in selected:
            item = self.pending_table.item(row_index, 0)
            data = item.data(Qt.UserRole) if item is not None else None
            if isinstance(data, dict):
                rows.append(data)
        return rows

    def _pallet_kg(self, pallet: dict) -> Decimal:
        return sum(
            (
                Decimal(str(allocation["quantity"]))
                * Decimal(str(allocation.get("peso_unitario_kg") or 0))
                for allocation in pallet.get("allocations") or []
            ),
            Decimal("0"),
        )

    def _active_pallet(self, *, create_if_missing: bool = True) -> dict | None:
        if self._selected_sequence is not None:
            try:
                return self._pallet(self._selected_sequence)
            except StopIteration:
                self._selected_sequence = None
        if not create_if_missing:
            return None
        sequence = max((int(p["sequence"]) for p in self._pallets), default=0) + 1
        pallet = {"sequence": sequence, "pallet_type_id": None, "locked": False, "allocations": []}
        self._pallets.append(pallet)
        self._selected_sequence = sequence
        return pallet

    def _row_models(self, row: dict):
        destination = self._destination(int(row["address_id"]))
        product_draft = next(
            product
            for product in destination.get("products") or []
            if int(product["product_id"]) == int(row["product_id"])
        )
        product = Product.get_by_id(int(row["product_id"]))
        return destination, product_draft, product

    def _add_row_to_pallet(self, pallet: dict, row: dict, quantity: Decimal) -> None:
        destination, product_draft, product = self._row_models(row)
        self._add_allocation_to_pallet(
            pallet, destination, product_draft, product, quantity
        )

    def _available_kg(self, pallet: dict) -> Decimal | None:
        max_kg = PalletCapacityService.pallet_max_kg()
        if max_kg is None:
            return None
        return max(max_kg - self._pallet_kg(pallet), Decimal("0"))

    def add_selected_to_current_pallet(self) -> bool:
        rows = self._selected_pending_rows()
        if not rows:
            self.issue_label.show_warning("Seleccione mercaderia pendiente para agregar al pallet.")
            return False
        pallet = self._active_pallet()
        if pallet is None:
            return False
        if int(pallet["sequence"]) in self._locked_sequences:
            self.issue_label.show_warning("El pallet actual esta fijado. Libere el pallet o cree uno nuevo.")
            return False
        available_kg = self._available_kg(pallet)
        if available_kg is None:
            self.issue_label.show_warning("Configure Kg/pallet antes de cargar mercaderia.")
            return False
        required_kg = sum((row["pending"] * row["unit_kg"] for row in rows), Decimal("0"))
        if required_kg > available_kg:
            self.issue_label.show_warning(
                "La seleccion no entra completa en el pallet actual. Use Agregar parcial o Distribuir automaticamente."
            )
            return False
        for row in rows:
            self._add_row_to_pallet(pallet, row, Decimal(str(row["pending"])))
        self._refresh()
        self.composition_changed.emit()
        return True

    def add_selected_partial(self) -> bool:
        rows = self._selected_pending_rows()
        if len(rows) != 1:
            self.issue_label.show_warning("Seleccione exactamente una linea para agregar una cantidad parcial.")
            return False
        row = rows[0]
        pallet = self._active_pallet()
        if pallet is None:
            return False
        if int(pallet["sequence"]) in self._locked_sequences:
            self.issue_label.show_warning("El pallet actual esta fijado. Libere el pallet o cree uno nuevo.")
            return False
        available_kg = self._available_kg(pallet)
        if available_kg is None:
            self.issue_label.show_warning("Configure Kg/pallet antes de cargar mercaderia.")
            return False
        unit_kg = Decimal(str(row["unit_kg"]))
        if unit_kg <= 0:
            self.issue_label.show_error("El articulo seleccionado no tiene un peso valido.")
            return False
        max_quantity = min(Decimal(str(row["pending"])), available_kg / unit_kg)
        if max_quantity <= 0:
            self.issue_label.show_warning("El pallet actual no tiene capacidad disponible.")
            return False
        value, accepted = QInputDialog.getDouble(
            self,
            "Agregar cantidad parcial",
            f"Cantidad a agregar (maximo {_quantity_text(max_quantity)}):",
            float(max_quantity),
            0.001,
            float(max_quantity),
            3,
        )
        if not accepted:
            return False
        self._add_row_to_pallet(pallet, row, Decimal(str(value)))
        self._refresh()
        self.composition_changed.emit()
        return True

    def mark_selected_as_loose(self) -> bool:
        """#767: deja la mercaderia seleccionada fuera de todo pallet.

        La mercaderia suelta viaja en el camion pero no va en ningun pallet.
        El backend ya la soporta (LoadOrderLooseAllocation); lo que faltaba
        era la via de operacion desde la pantalla guiada.
        """
        rows = self._selected_pending_rows()
        if len(rows) != 1:
            self.issue_label.show_warning(
                "Seleccione exactamente una línea para marcarla como suelta."
            )
            return False
        row = rows[0]
        pending = Decimal(str(row["pending"]))
        if pending <= 0:
            self.issue_label.show_warning(
                "La línea seleccionada no tiene mercadería pendiente."
            )
            return False
        value, accepted = QInputDialog.getDouble(
            self,
            "Marcar como suelta",
            f"Cantidad a despachar suelta (máximo {_quantity_text(pending)}):",
            float(pending),
            0.001,
            float(pending),
            3,
        )
        if not accepted:
            return False
        quantity = Decimal(str(value)).quantize(Decimal("0.001"))
        if quantity <= 0 or quantity > pending:
            self.issue_label.show_warning(
                "La cantidad suelta no puede superar lo pendiente de la línea."
            )
            return False
        self.add_loose_allocation(
            int(row["address_id"]), int(row["product_id"]), quantity
        )
        self.issue_label.show_success(
            f"{_quantity_text(quantity)} marcadas como mercadería suelta."
        )
        return True

    def distribute_selected_automatically(self) -> bool:
        rows = self._selected_pending_rows()
        if len(rows) != 1:
            self.issue_label.show_warning("Seleccione exactamente una linea para distribuir automaticamente.")
            return False
        row = rows[0]
        max_kg = PalletCapacityService.pallet_max_kg()
        if max_kg is None:
            self.issue_label.show_warning("Configure Kg/pallet antes de distribuir automaticamente.")
            return False
        unit_kg = Decimal(str(row["unit_kg"]))
        if unit_kg <= 0:
            self.issue_label.show_error("El articulo seleccionado no tiene un peso valido.")
            return False
        if unit_kg > max_kg:
            self.issue_label.show_error("Una unidad del articulo supera el maximo permitido por pallet.")
            return False
        pending = Decimal(str(row["pending"]))
        quantity_per_pallet = (max_kg / unit_kg).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
        if quantity_per_pallet <= 0:
            return False
        pallet_count = int((pending / quantity_per_pallet).to_integral_value(rounding=ROUND_CEILING))
        empty_unlocked = [
            pallet
            for pallet in sorted(self._pallets, key=lambda item: int(item["sequence"]))
            if not pallet.get("allocations")
            and int(pallet["sequence"]) not in self._locked_sequences
        ]
        next_sequence = max((int(p["sequence"]) for p in self._pallets), default=0) + 1
        while len(empty_unlocked) < pallet_count:
            pallet = {
                "sequence": next_sequence,
                "pallet_type_id": None,
                "locked": False,
                "allocations": [],
            }
            self._pallets.append(pallet)
            empty_unlocked.append(pallet)
            next_sequence += 1
        remaining = pending
        used = []
        for pallet in empty_unlocked[:pallet_count]:
            quantity = min(remaining, quantity_per_pallet)
            self._add_row_to_pallet(pallet, row, quantity)
            remaining -= quantity
            used.append(pallet)
            if remaining <= 0:
                break
        self._selected_sequence = int(used[0]["sequence"]) if used else self._selected_sequence
        self._refresh()
        self.composition_changed.emit()
        self.issue_label.show_success(
            f"{_quantity_text(pending)} unidades distribuidas en {len(used)} pallets."
        )
        return True

    def propose_remainder(self) -> bool:
        max_kg = PalletCapacityService.pallet_max_kg()
        if max_kg is None:
            self.issue_label.show_warning("Configure Kg/pallet antes de proponer el resto.")
            return False
        planning = self._planning_destinations()
        weights = self._product_weights()
        total_kg = Decimal("0")
        for destination in planning:
            for product in destination.get("products") or []:
                weight = weights.get(int(product["product_id"]), Decimal("0"))
                if weight <= 0:
                    self.issue_label.show_error(
                        f"El articulo {product.get('product_label') or product['product_id']} no tiene un peso valido."
                    )
                    return False
                total_kg += Decimal(str(product.get("quantity") or 0)) * weight
        locked_pallets = [
            pallet for pallet in self._pallets if int(pallet["sequence"]) in self._locked_sequences
        ]
        locked_kg = sum((self._pallet_kg(pallet) for pallet in locked_pallets), Decimal("0"))
        remaining_kg = max(total_kg - locked_kg, Decimal("0"))
        unlocked_needed = int((remaining_kg / max_kg).to_integral_value(rounding=ROUND_CEILING)) if remaining_kg else 0
        target_count = len(locked_pallets) + unlocked_needed
        temp_pallets = self.pallet_drafts()
        next_sequence = max((int(p["sequence"]) for p in temp_pallets), default=0) + 1
        while len(temp_pallets) < target_count:
            temp_pallets.append(
                {"sequence": next_sequence, "pallet_type_id": None, "locked": False, "allocations": []}
            )
            next_sequence += 1
        try:
            prepared = PalletPreparationPlanner().propose(
                destinations=planning,
                pallets=temp_pallets,
                product_weights=weights,
                max_kg_per_pallet=max_kg,
                locked_sequences=set(self._locked_sequences),
                preserve_unlocked_allocations=False,
            )
        except ValueError as exc:
            self.issue_label.show_error(str(exc))
            return False
        if not prepared.is_complete:
            self.issue_label.show_warning("No se pudo completar la propuesta con la capacidad disponible.")
            return False
        self._prepared_proposal = prepared
        self.accept_prepared_proposal()
        self.issue_label.show_success("Se completo la propuesta respetando los pallets fijados.")
        return True

    def remove_selected_from_current_pallet(self) -> bool:
        pallet = self._active_pallet(create_if_missing=False)
        if pallet is None:
            return False
        if int(pallet["sequence"]) in self._locked_sequences:
            self.issue_label.show_warning("El pallet actual esta fijado. Libere el pallet antes de modificarlo.")
            return False
        row = self.guided_content_table.currentRow()
        item = self.guided_content_table.item(row, 0) if row >= 0 else None
        allocation_index = item.data(Qt.UserRole) if item is not None else None
        if allocation_index is None:
            self.issue_label.show_warning("Seleccione una linea del pallet para quitarla.")
            return False
        if 0 <= int(allocation_index) < len(pallet["allocations"]):
            pallet["allocations"].pop(int(allocation_index))
            self._refresh()
            self.composition_changed.emit()
            return True
        return False

    def _guided_pending_double_click(self, row: int, _column: int) -> None:
        self.pending_table.selectRow(row)
        self.add_selected_to_current_pallet()

    def _guided_content_double_click(self, row: int, _column: int) -> None:
        self.guided_content_table.selectRow(row)
        self.remove_selected_from_current_pallet()

    def _guided_new_pallet(self) -> None:
        sequence = max((int(p["sequence"]) for p in self._pallets), default=0) + 1
        self._pallets.append(
            {"sequence": sequence, "pallet_type_id": None, "locked": False, "allocations": []}
        )
        self._selected_sequence = sequence
        self._refresh()
        self.composition_changed.emit()

    def _guided_combo_changed(self) -> None:
        sequence = self.guided_pallet_combo.currentData()
        if sequence is None:
            return
        self._selected_sequence = int(sequence)
        self._render_editor()
        self._refresh_guided_ui()

    def toggle_selected_pallet_lock(self) -> None:
        super().toggle_selected_pallet_lock()
        if getattr(self, "_guided_ready", False):
            self._refresh_guided_ui()

    def _guided_remove_loose(self, index: int) -> None:
        """#767: la mercaderia suelta vuelve a quedar pendiente."""
        self.remove_loose_allocation(index)
        self.issue_label.show_success(
            "Mercadería suelta quitada: vuelve a quedar pendiente de preparar."
        )

    def _render_guided_loose_table(self) -> None:
        if not hasattr(self, "guided_loose_table"):
            return
        for row in range(self.guided_loose_table.rowCount()):
            button = self.guided_loose_table.cellWidget(row, 4)
            if button is not None:
                self.guided_loose_table.removeCellWidget(row, 4)
                button.setParent(None)
                button.deleteLater()
        has_loose = bool(self._loose)
        self.guided_loose_group.setVisible(has_loose)
        self.guided_loose_table.setRowCount(len(self._loose))
        for row_index, allocation in enumerate(self._loose):
            destination = self._destination(int(allocation["address_id"]))
            quantity = Decimal(str(allocation["quantity"]))
            kilos = quantity * Decimal(str(allocation.get("peso_unitario_kg") or 0))
            values = (
                f"{destination.get('client_label', '')} · {destination.get('address_label', '')}",
                allocation.get("product_label") or str(allocation["product_id"]),
                _quantity_text(quantity),
                _kg_text(kilos),
            )
            for column, value in enumerate(values):
                self.guided_loose_table.setItem(
                    row_index, column, QTableWidgetItem(str(value))
                )
            remove_button = QPushButton("Quitar")
            remove_button.setObjectName(f"guidedRemoveLooseButton_{row_index}")
            remove_button.setToolTip("Quitar esta mercadería suelta")
            remove_button.clicked.connect(
                lambda _checked=False, loose_row=row_index: self._guided_remove_loose(
                    loose_row
                )
            )
            self.guided_loose_table.setCellWidget(row_index, 4, remove_button)

    def _refresh_guided_ui(self) -> None:
        if not hasattr(self, "guided_pallet_combo"):
            return
        self._render_guided_loose_table()
        selected = self._selected_sequence
        self.guided_pallet_combo.blockSignals(True)
        self.guided_pallet_combo.clear()
        if not self._pallets:
            self.guided_pallet_combo.addItem("(sin pallets)", None)
        else:
            for pallet in sorted(self._pallets, key=lambda item: int(item["sequence"])):
                sequence = int(pallet["sequence"])
                suffix = " - FIJADO" if sequence in self._locked_sequences else ""
                self.guided_pallet_combo.addItem(f"Pallet {sequence}{suffix}", sequence)
            index = self.guided_pallet_combo.findData(selected)
            if index < 0:
                index = 0
                self._selected_sequence = int(self.guided_pallet_combo.itemData(0))
            self.guided_pallet_combo.setCurrentIndex(index)
        self.guided_pallet_combo.blockSignals(False)

        pallet = self._active_pallet(create_if_missing=False)
        self.guided_content_table.setRowCount(0)
        if pallet is None:
            self.guided_totals_label.setText("Sin pallet actual. Cree uno o agregue mercaderia para comenzar.")
            self.guided_remove_button.setEnabled(False)
            self.guided_lock_button.setEnabled(False)
            return
        total_kg = Decimal("0")
        for row_index, allocation in enumerate(pallet.get("allocations") or []):
            destination = self._destination(int(allocation["address_id"]))
            quantity = Decimal(str(allocation["quantity"]))
            kilos = quantity * Decimal(str(allocation.get("peso_unitario_kg") or 0))
            total_kg += kilos
            self.guided_content_table.insertRow(row_index)
            values = (
                allocation.get("product_label") or str(allocation["product_id"]),
                f"{destination.get('client_label', '')} / {destination.get('address_label', '')}",
                _quantity_text(quantity),
                _kg_text(kilos),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row_index)
                self.guided_content_table.setItem(row_index, column, item)
        # Ver `PalletCompositionWidget._refresh_guided_ui`: sin base disponible la
        # capacidad se trata como no configurada y el total se muestra sin tope.
        try:
            max_kg = PalletCapacityService.pallet_max_kg()
        except Exception:
            max_kg = None
        capacity = f" / {_kg_text(max_kg)}" if max_kg else ""
        self.guided_totals_label.setText(
            f"Pallet {pallet['sequence']}: {len(pallet.get('allocations') or [])} lineas · {_kg_text(total_kg)}{capacity}"
        )
        locked = int(pallet["sequence"]) in self._locked_sequences
        self.guided_lock_button.setText("Liberar pallet" if locked else "Fijar pallet")
        self.guided_lock_button.setEnabled(True)
        self.guided_remove_button.setEnabled(bool(pallet.get("allocations")) and not locked)

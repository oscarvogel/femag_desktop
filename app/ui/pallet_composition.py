from __future__ import annotations

from decimal import Decimal

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Product
from app.services.pallet_capacity_service import PalletCapacityService
from app.services.pallet_preparation_planner import PalletPreparationPlanner
from app.ui.pallet_composition_legacy import *  # noqa: F401,F403
from app.ui.pallet_composition_legacy import (
    PalletCompositionWidget as _LegacyPalletCompositionWidget,
    _kg_text,
    _quantity_text,
)


class PalletCompositionWidget(_LegacyPalletCompositionWidget):
    """Preparacion de pallets con propuesta automatica revisable.

    Conserva el comportamiento operativo existente y agrega una capa de UX
    para proponer, revisar y aceptar una distribucion antes de tocar el borrador
    actual. Los pallets fijados quedan fuera de las reorganizaciones.
    """

    def __init__(self, *, destinations: list[dict] | None = None, parent=None):
        self._prepared_proposal = None
        self._locked_sequences: set[int] = set()
        self._truck_max_load_kg: Decimal | None = None
        super().__init__(destinations=destinations, parent=parent)
        self._install_auto_distribution_ui()
        self.composition_changed.connect(self._invalidate_prepared_proposal)
        self._refresh_auto_distribution_ui()

    def _refresh(self) -> None:
        super()._refresh()
        if hasattr(self, "pending_table"):
            self._refresh_auto_distribution_ui()

    def _install_auto_distribution_ui(self) -> None:
        total_layout = self.total_kg_label.parentWidget().layout()
        self.capacity_summary_label = QLabel("")
        self.capacity_summary_label.setObjectName("palletCapacitySummary")
        self.capacity_summary_label.setAlignment(Qt.AlignCenter)
        self.capacity_summary_label.setStyleSheet(
            "color: #d9e7f2; background: transparent; border: 0; font-weight: 600;"
        )
        total_layout.addWidget(self.capacity_summary_label)

        batch_frame = self.findChild(QFrame, "palletBatchActions")
        batch_layout = batch_frame.layout()
        self.propose_distribution_button = QPushButton("Proponer distribucion automatica")
        self.propose_distribution_button.setObjectName("proposePalletDistributionButton")
        self.propose_distribution_button.clicked.connect(self.propose_distribution)
        batch_layout.addWidget(self.propose_distribution_button, 3, 0, 1, 2)

        self.reorganize_pending_button = QPushButton("Reorganizar pendientes")
        self.reorganize_pending_button.setObjectName("reorganizePendingPalletsButton")
        self.reorganize_pending_button.setProperty("secondary", True)
        self.reorganize_pending_button.clicked.connect(self.reorganize_pending)
        batch_layout.addWidget(self.reorganize_pending_button, 4, 0, 1, 2)

        editor_layout = self.editor_title.parentWidget().layout()
        self.lock_pallet_button = QPushButton("Fijar pallet")
        self.lock_pallet_button.setObjectName("togglePalletLockButton")
        self.lock_pallet_button.setProperty("secondary", True)
        self.lock_pallet_button.clicked.connect(self.toggle_selected_pallet_lock)
        editor_layout.insertWidget(1, self.lock_pallet_button)

        proposal_tab = QWidget()
        proposal_tab.setObjectName("palletEditorTabProposal")
        proposal_layout = QVBoxLayout(proposal_tab)
        proposal_layout.setContentsMargins(0, 8, 0, 0)
        self.proposal_feedback = QLabel("Genere una propuesta para revisarla antes de aplicarla.")
        self.proposal_feedback.setObjectName("palletProposalFeedback")
        self.proposal_feedback.setWordWrap(True)
        proposal_layout.addWidget(self.proposal_feedback)
        self.proposal_table = QTableWidget(0, 6)
        self.proposal_table.setObjectName("palletDistributionProposalTable")
        self.proposal_table.setHorizontalHeaderLabels(
            ("Pallet", "Kg", "Ocupacion", "Clientes", "Productos", "Estado")
        )
        self.proposal_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.proposal_table.verticalHeader().setVisible(False)
        self.proposal_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.proposal_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        proposal_layout.addWidget(self.proposal_table, 1)
        self.accept_proposal_button = QPushButton("Aceptar distribucion")
        self.accept_proposal_button.setObjectName("acceptPalletDistributionButton")
        self.accept_proposal_button.clicked.connect(self.accept_prepared_proposal)
        proposal_layout.addWidget(self.accept_proposal_button)
        self.cancel_proposal_button = QPushButton("Cancelar propuesta")
        self.cancel_proposal_button.setObjectName("cancelPalletDistributionButton")
        self.cancel_proposal_button.setProperty("secondary", True)
        self.cancel_proposal_button.clicked.connect(self.cancel_prepared_proposal)
        proposal_layout.addWidget(self.cancel_proposal_button)
        self.editor_tabs.addTab(proposal_tab, "Propuesta")
        self._proposal_tab_index = self.editor_tabs.indexOf(proposal_tab)

        pending_tab = QWidget()
        pending_tab.setObjectName("palletEditorTabPending")
        pending_layout = QVBoxLayout(pending_tab)
        pending_layout.setContentsMargins(0, 8, 0, 0)
        self.pending_table = QTableWidget(0, 8)
        self.pending_table.setObjectName("palletPendingTable")
        self.pending_table.setHorizontalHeaderLabels(
            ("Cliente", "Destino", "Articulo", "Pedido", "Asignado", "Suelto", "Pendiente", "Kg")
        )
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pending_table.verticalHeader().setVisible(False)
        self.pending_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        pending_layout.addWidget(self.pending_table, 1)
        self.editor_tabs.addTab(pending_tab, "Pendientes")

    def _planning_destinations(self) -> list[dict]:
        loose_by_key: dict[tuple[int, int], Decimal] = {}
        for allocation in self._loose:
            key = (int(allocation["address_id"]), int(allocation["product_id"]))
            loose_by_key[key] = loose_by_key.get(key, Decimal("0")) + Decimal(
                str(allocation["quantity"])
            )

        destinations: list[dict] = []
        for destination in self._destinations:
            products = []
            for product in destination.get("products") or []:
                key = (int(destination["address_id"]), int(product["product_id"]))
                quantity = Decimal(str(product.get("quantity") or 0)) - loose_by_key.get(
                    key, Decimal("0")
                )
                if quantity <= 0:
                    continue
                product_copy = dict(product)
                product_copy["quantity"] = quantity
                products.append(product_copy)
            destination_copy = dict(destination)
            destination_copy["products"] = products
            destinations.append(destination_copy)
        return destinations

    def _product_weights(self) -> dict[int, Decimal]:
        product_ids = {
            int(product["product_id"])
            for destination in self._destinations
            for product in destination.get("products") or []
        }
        weights = {}
        for product in Product.select().where(Product.id.in_(product_ids)):
            weights[int(product.id)] = Decimal(str(product.peso_unitario_kg or 0))
        return weights

    def _prepare_distribution(self, *, preserve_current: bool) -> None:
        max_kg = PalletCapacityService.pallet_max_kg()
        if max_kg is None:
            self.issue_label.show_warning(
                "Configure el maximo de kg por pallet antes de generar una distribucion automatica."
            )
            return
        try:
            prepared = PalletPreparationPlanner().propose(
                destinations=self._planning_destinations(),
                pallets=self.pallet_drafts(),
                product_weights=self._product_weights(),
                max_kg_per_pallet=max_kg,
                locked_sequences=set(self._locked_sequences),
                preserve_unlocked_allocations=preserve_current,
            )
        except ValueError as exc:
            self.issue_label.show_error(str(exc))
            return
        self._prepared_proposal = prepared
        self._render_prepared_proposal()
        self.editor_tabs.setCurrentIndex(self._proposal_tab_index)

    def propose_distribution(self) -> None:
        self._prepare_distribution(preserve_current=False)

    def reorganize_pending(self) -> None:
        self._prepare_distribution(preserve_current=True)

    def _render_prepared_proposal(self) -> None:
        prepared = self._prepared_proposal
        self.proposal_table.setRowCount(0)
        if prepared is None:
            self.proposal_feedback.setText("Genere una propuesta para revisarla antes de aplicarla.")
            self.accept_proposal_button.setEnabled(False)
            self.cancel_proposal_button.setEnabled(False)
            return
        max_kg = prepared.proposal.max_kg_per_pallet
        for row, pallet in enumerate(prepared.proposal.pallets):
            self.proposal_table.insertRow(row)
            occupation = (pallet.total_kg / max_kg * Decimal("100")) if max_kg else Decimal("0")
            values = (
                str(pallet.sequence),
                _kg_text(pallet.total_kg),
                f"{occupation.quantize(Decimal('0.1'))}%",
                str(pallet.client_count),
                str(pallet.product_count),
                "Fijado" if pallet.locked else "Propuesto",
            )
            for column, value in enumerate(values):
                self.proposal_table.setItem(row, column, QTableWidgetItem(value))
        if prepared.is_complete:
            self.proposal_feedback.setText(
                "Propuesta completa. Revise los pallets y acepte para aplicar la distribucion."
            )
        else:
            pending_kg = sum(
                (Decimal(str(row["pending_kg"])) for row in prepared.pending_rows),
                Decimal("0"),
            )
            self.proposal_feedback.setText(
                f"La capacidad disponible no alcanza: quedan {_kg_text(pending_kg)} pendientes."
            )
        self.accept_proposal_button.setEnabled(prepared.is_complete)
        self.cancel_proposal_button.setEnabled(True)

    def accept_prepared_proposal(self) -> None:
        prepared = self._prepared_proposal
        if prepared is None or not prepared.is_complete:
            return
        pallet_types = {
            int(pallet["sequence"]): pallet.get("pallet_type_id") for pallet in self._pallets
        }
        self._pallets = []
        self._locked_sequences = set()
        for draft in prepared.pallet_drafts:
            sequence = int(draft["sequence"])
            self._pallets.append(
                {
                    "sequence": sequence,
                    "pallet_type_id": draft.get("pallet_type_id") or pallet_types.get(sequence),
                    "locked": bool(draft.get("locked")),
                    "allocations": [dict(allocation) for allocation in draft.get("allocations") or []],
                }
            )
            if draft.get("locked"):
                self._locked_sequences.add(sequence)
        self._prepared_proposal = None
        self._selected_sequence = self._pallets[0]["sequence"] if self._pallets else None
        self._refresh()
        self.composition_changed.emit()

    def cancel_prepared_proposal(self) -> None:
        self._prepared_proposal = None
        self._render_prepared_proposal()

    def _invalidate_prepared_proposal(self) -> None:
        if self._prepared_proposal is None:
            return
        self._prepared_proposal = None
        self._render_prepared_proposal()

    def toggle_selected_pallet_lock(self) -> None:
        sequence = self._selected_sequence
        if sequence is None:
            return
        if sequence in self._locked_sequences:
            self._locked_sequences.remove(sequence)
        else:
            self._locked_sequences.add(sequence)
        pallet = self._pallet(sequence)
        pallet["locked"] = sequence in self._locked_sequences
        self._refresh_auto_distribution_ui()
        self.composition_changed.emit()

    def load_pallets(self, pallets: list[dict], *, loose: list[dict] | None = None) -> None:
        locked = {int(pallet["sequence"]) for pallet in pallets if pallet.get("locked")}
        super().load_pallets(pallets, loose=loose)
        self._locked_sequences = locked
        for pallet in self._pallets:
            pallet["locked"] = int(pallet["sequence"]) in locked
        if hasattr(self, "pending_table"):
            self._refresh_auto_distribution_ui()

    def pallet_drafts(self) -> list[dict]:
        drafts = super().pallet_drafts()
        for draft in drafts:
            draft["locked"] = int(draft["sequence"]) in self._locked_sequences
        return drafts

    def set_truck_capacity_kg(self, value) -> None:
        if value in (None, "", 0):
            self._truck_max_load_kg = None
        else:
            self._truck_max_load_kg = Decimal(str(value)).quantize(Decimal("0.001"))
        if hasattr(self, "capacity_summary_label"):
            self._refresh_auto_distribution_ui()

    def _current_rows(self) -> list[dict]:
        assigned_by_key: dict[tuple[int, int], Decimal] = {}
        loose_by_key: dict[tuple[int, int], Decimal] = {}
        for pallet in self._pallets:
            for allocation in pallet["allocations"]:
                key = (int(allocation["address_id"]), int(allocation["product_id"]))
                assigned_by_key[key] = assigned_by_key.get(key, Decimal("0")) + Decimal(
                    str(allocation["quantity"])
                )
        for allocation in self._loose:
            key = (int(allocation["address_id"]), int(allocation["product_id"]))
            loose_by_key[key] = loose_by_key.get(key, Decimal("0")) + Decimal(
                str(allocation["quantity"])
            )
        weights = self._product_weights()
        rows = []
        for destination in self._destinations:
            for product in destination.get("products") or []:
                key = (int(destination["address_id"]), int(product["product_id"]))
                requested = Decimal(str(product.get("quantity") or 0))
                assigned = assigned_by_key.get(key, Decimal("0"))
                loose = loose_by_key.get(key, Decimal("0"))
                pending = max(requested - assigned - loose, Decimal("0"))
                unit_kg = weights.get(int(product["product_id"]), Decimal("0"))
                rows.append(
                    {
                        "client": destination.get("client_label", ""),
                        "destination": destination.get("address_label", ""),
                        "product": product.get("product_label", ""),
                        "requested": requested,
                        "assigned": assigned,
                        "loose": loose,
                        "pending": pending,
                        "pending_kg": pending * unit_kg,
                    }
                )
        return rows

    def _render_pending_table(self) -> None:
        rows = self._current_rows()
        self.pending_table.setRowCount(0)
        for row_index, row in enumerate(rows):
            self.pending_table.insertRow(row_index)
            values = (
                row["client"],
                row["destination"],
                row["product"],
                _quantity_text(row["requested"]),
                _quantity_text(row["assigned"]),
                _quantity_text(row["loose"]),
                _quantity_text(row["pending"]),
                _kg_text(row["pending_kg"]),
            )
            for column, value in enumerate(values):
                self.pending_table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def _refresh_auto_distribution_ui(self) -> None:
        try:
            max_kg = PalletCapacityService.pallet_max_kg()
        except Exception:
            max_kg = None
        total_kg = Decimal("0")
        for pallet in self._pallets:
            pallet_kg = sum(
                (
                    Decimal(str(allocation["quantity"]))
                    * Decimal(str(allocation.get("peso_unitario_kg") or 0))
                    for allocation in pallet["allocations"]
                ),
                Decimal("0"),
            )
            total_kg += pallet_kg
            card = self._cards.get(int(pallet["sequence"]))
            if card is not None:
                locked = int(pallet["sequence"]) in self._locked_sequences
                card.title_label.setText(
                    f"PALLET {pallet['sequence']}{'  🔒' if locked else ''}"
                )
                if max_kg:
                    occupation = (pallet_kg / max_kg * Decimal("100")) if max_kg else Decimal("0")
                    base_status = card.status_label.text().split(" · ")[0]
                    card.status_label.setText(
                        f"{base_status} · {occupation.quantize(Decimal('1'))}%"
                        + (" · Fijado" if locked else "")
                    )
        loose_kg = sum(
            (
                Decimal(str(allocation["quantity"]))
                * Decimal(str(allocation.get("peso_unitario_kg") or 0))
                for allocation in self._loose
            ),
            Decimal("0"),
        )
        transport_kg = total_kg + loose_kg
        parts = []
        if max_kg:
            parts.append(f"Maximo por pallet: {_kg_text(max_kg)}")
        else:
            parts.append("Maximo por pallet: sin configurar")
        if self._truck_max_load_kg:
            margin = self._truck_max_load_kg - transport_kg
            if margin >= 0:
                parts.append(
                    f"Camion: {_kg_text(transport_kg)} / {_kg_text(self._truck_max_load_kg)} · margen {_kg_text(margin)}"
                )
            else:
                parts.append(
                    f"Camion excedido por {_kg_text(-margin)}"
                )
        self.capacity_summary_label.setText(" · ".join(parts))
        self.propose_distribution_button.setEnabled(bool(self._pallets))
        self.reorganize_pending_button.setEnabled(bool(self._pallets))
        self.lock_pallet_button.setEnabled(self._selected_sequence is not None)
        if self._selected_sequence in self._locked_sequences:
            self.lock_pallet_button.setText("Liberar pallet")
        else:
            self.lock_pallet_button.setText("Fijar pallet")
        self._render_pending_table()
        self._render_prepared_proposal()

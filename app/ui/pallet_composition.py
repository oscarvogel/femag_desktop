from __future__ import annotations

from decimal import Decimal

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.masters import Product
from app.services.pallet_composition_service import (
    AllocationDraft,
    PalletCompositionService,
    PalletDraft,
    RequestedLine,
)


def _kg_text(value) -> str:
    decimal_value = Decimal(str(value)).quantize(Decimal("0.001"))
    whole, fraction = f"{decimal_value:.3f}".split(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{grouped},{fraction} kg"


class PalletCard(QFrame):
    selected = pyqtSignal(int)

    def __init__(self, sequence: int, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.setObjectName(f"palletCard{sequence}")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(180, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.title_label = QLabel(f"PALLET {sequence}")
        self.title_label.setStyleSheet("font-weight: 800; font-size: 15px;")
        self.kg_label = QLabel("0,000 kg")
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
            "border-radius: 14px; }} QLabel { border: none; background: transparent; }"
        )


class PalletCompositionWidget(QWidget):
    def __init__(self, *, destinations: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("palletCompositionWidget")
        self._destinations: list[dict] = destinations or []
        self._pallets: list[dict] = []
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
            "QFrame#loadOrderKgTotalFrame { background: #173a59; border-radius: 12px; } "
            "QLabel { color: white; }"
        )
        total_layout = QVBoxLayout(total_frame)
        total_caption = QLabel("TOTAL DE LA ORDEN")
        total_caption.setAlignment(Qt.AlignCenter)
        self.total_kg_label = QLabel("0,000 kg")
        self.total_kg_label.setObjectName("loadOrderTotalKg")
        self.total_kg_label.setAlignment(Qt.AlignCenter)
        self.total_kg_label.setStyleSheet("font-size: 38px; font-weight: 900;")
        self.summary_label = QLabel("0 pallets · 0 completos · 0 pendientes")
        self.summary_label.setObjectName("loadOrderPalletSummary")
        self.summary_label.setAlignment(Qt.AlignCenter)
        total_layout.addWidget(total_caption)
        total_layout.addWidget(self.total_kg_label)
        total_layout.addWidget(self.summary_label)
        left_layout.addWidget(total_frame)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.card_container = QWidget()
        self.card_grid = QGridLayout(self.card_container)
        self.card_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.card_grid.setSpacing(10)
        scroll.setWidget(self.card_container)
        left_layout.addWidget(scroll, 1)

        add_pallet_button = QPushButton("+ Agregar pallet")
        add_pallet_button.setObjectName("addPalletCardButton")
        add_pallet_button.clicked.connect(self.add_pallet)
        left_layout.addWidget(add_pallet_button)

        self.issue_label = QLabel("")
        self.issue_label.setObjectName("palletCompositionIssues")
        self.issue_label.setWordWrap(True)
        left_layout.addWidget(self.issue_label)
        root.addWidget(left, 3)

        self.editor_panel = QFrame()
        self.editor_panel.setObjectName("palletEditorPanel")
        self.editor_panel.setMinimumWidth(300)
        editor = QVBoxLayout(self.editor_panel)
        self.editor_title = QLabel("Seleccione un pallet")
        self.editor_title.setStyleSheet("font-size: 17px; font-weight: 800;")
        editor.addWidget(self.editor_title)
        editor.addWidget(QLabel("Cliente / destino"))
        self.destination_combo = QComboBox()
        self.destination_combo.setObjectName("palletDestinationInput")
        editor.addWidget(self.destination_combo)
        editor.addWidget(QLabel("Articulo"))
        self.product_combo = QComboBox()
        self.product_combo.setObjectName("palletProductInput")
        editor.addWidget(self.product_combo)
        editor.addWidget(QLabel("Cantidad"))
        self.quantity_input = QDoubleSpinBox()
        self.quantity_input.setObjectName("palletAllocationQuantityInput")
        self.quantity_input.setRange(0.001, 999999999)
        self.quantity_input.setDecimals(3)
        editor.addWidget(self.quantity_input)
        add_allocation_button = QPushButton("Agregar mercaderia")
        add_allocation_button.setObjectName("addPalletAllocationButton")
        add_allocation_button.clicked.connect(self._add_from_editor)
        editor.addWidget(add_allocation_button)
        self.allocation_table = QTableWidget(0, 4)
        self.allocation_table.setObjectName("palletAllocationTable")
        self.allocation_table.setHorizontalHeaderLabels(("Cliente / destino", "Articulo", "Cantidad", "Kg"))
        self.allocation_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.allocation_table.verticalHeader().setVisible(False)
        editor.addWidget(self.allocation_table, 1)
        remove_button = QPushButton("Quitar asignacion")
        remove_button.setObjectName("removePalletAllocationButton")
        remove_button.clicked.connect(self._remove_selected_allocation)
        editor.addWidget(remove_button)
        self.destination_combo.currentIndexChanged.connect(self._refresh_product_combo)
        root.addWidget(self.editor_panel, 2)

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
        self._refresh_destination_combo()
        self._refresh()

    def add_pallet(self) -> int:
        sequence = max((pallet["sequence"] for pallet in self._pallets), default=0) + 1
        self._pallets.append({"sequence": sequence, "pallet_type_id": None, "allocations": []})
        self._selected_sequence = sequence
        self._refresh()
        return sequence

    def add_allocation(self, sequence: int, address_id: int, product_id: int, quantity) -> None:
        pallet = self._pallet(sequence)
        destination = self._destination(address_id)
        product_draft = next(
            product for product in destination.get("products") or [] if product["product_id"] == product_id
        )
        product = Product.get_by_id(product_id)
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
        self._selected_sequence = sequence
        self._refresh()

    def load_pallets(self, pallets: list[dict]) -> None:
        self._pallets = []
        for pallet in pallets:
            self._pallets.append(
                {
                    "sequence": pallet["sequence"],
                    "pallet_type_id": pallet.get("pallet_type_id"),
                    "allocations": [dict(allocation) for allocation in pallet.get("allocations") or []],
                }
            )
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

    def _refresh(self) -> None:
        result = PalletCompositionService().reconcile(
            requested=self._requested_lines(),
            pallets=self._domain_pallets(),
        )
        self.total_kg_label.setText(_kg_text(result.total_kg))
        invalid_keys = {
            (issue.destination_id, issue.product_id)
            for issue in result.issues
            if issue.code == "excess"
        }
        pending_keys = {
            (issue.destination_id, issue.product_id)
            for issue in result.issues
            if issue.code in {"pending", "zero_weight"}
        }
        states = {}
        for pallet in self._pallets:
            keys = {(item["address_id"], item["product_id"]) for item in pallet["allocations"]}
            if keys & invalid_keys:
                states[pallet["sequence"]] = "invalid"
            elif not keys or keys & pending_keys:
                states[pallet["sequence"]] = "incomplete"
            else:
                states[pallet["sequence"]] = "complete"
        complete_count = sum(state == "complete" for state in states.values())
        pending_count = len(self._pallets) - complete_count
        self.summary_label.setText(
            f"{len(self._pallets)} pallets · {complete_count} "
            f"{'completo' if complete_count == 1 else 'completos'} · {pending_count} "
            f"{'pendiente' if pending_count == 1 else 'pendientes'}"
        )
        self.issue_label.setText("\n".join(issue.message for issue in result.issues))
        while self.card_grid.count():
            item = self.card_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cards = {}
        result_by_sequence = {pallet.sequence: pallet for pallet in result.pallets}
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
        self._render_editor()

    def _select_pallet(self, sequence: int) -> None:
        self._selected_sequence = sequence
        self._render_editor()

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
        self._refresh_product_combo()

    def _refresh_product_combo(self) -> None:
        address_id = self.destination_combo.currentData()
        self.product_combo.clear()
        self.product_combo.addItem("", None)
        if address_id is None:
            return
        destination = self._destination(address_id)
        for product in destination.get("products") or []:
            self.product_combo.addItem(product["product_label"], product["product_id"])

    def _add_from_editor(self) -> None:
        if self._selected_sequence is None:
            return
        address_id = self.destination_combo.currentData()
        product_id = self.product_combo.currentData()
        if address_id is None or product_id is None:
            return
        self.add_allocation(self._selected_sequence, address_id, product_id, self.quantity_input.value())

    def _remove_selected_allocation(self) -> None:
        if self._selected_sequence is None:
            return
        row = self.allocation_table.currentRow()
        pallet = self._pallet(self._selected_sequence)
        if 0 <= row < len(pallet["allocations"]):
            pallet["allocations"].pop(row)
            self._refresh()

    def _render_editor(self) -> None:
        if self._selected_sequence is None:
            self.editor_title.setText("Seleccione un pallet")
            self.allocation_table.setRowCount(0)
            return
        pallet = self._pallet(self._selected_sequence)
        self.editor_title.setText(f"PALLET {self._selected_sequence}")
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

import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _destinations(db):
    from app.models.masters import Client, ClientAddress, Product

    client_a = Client.create(name="Cliente UI pallet A", cuit="30700000301", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino A",
    )
    client_b = Client.create(name="Cliente UI pallet B", cuit="30700000302", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Destino B",
    )
    product_a = Product.create(
        name="Articulo UI pallet A",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    product_b = Product.create(
        name="Articulo UI pallet B",
        unit="unidad",
        peso_unitario_kg=Decimal("10.000"),
    )
    return [
        {
            "client_id": client_a.id,
            "address_id": address_a.id,
            "client_label": client_a.name,
            "address_label": address_a.address,
            "products": [
                {
                    "product_id": product_a.id,
                    "product_label": product_a.name,
                    "quantity": 40,
                    "unit": product_a.unit,
                }
            ],
        },
        {
            "client_id": client_b.id,
            "address_id": address_b.id,
            "client_label": client_b.name,
            "address_label": address_b.address,
            "products": [
                {
                    "product_id": product_b.id,
                    "product_label": product_b.name,
                    "quantity": 5,
                    "unit": product_b.unit,
                }
            ],
        },
    ]


def test_empty_state_guides_first_pallet_and_disables_editor_actions(db):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=_destinations(db))
    app.processEvents()

    empty_state = widget.findChild(QLabel, "palletCompositionEmptyState")
    assert "Todavia no agregaste pallets" in empty_state.text()
    assert "45 unidades pendientes" in empty_state.text()
    assert widget.summary_label.text() == "45 unidades pendientes"
    assert widget.quantity_input.value() == 1
    assert widget.findChild(QPushButton, "addPalletCardButton").text() == "Agregar primer pallet"
    assert widget.destination_combo.isEnabled() is False
    assert widget.product_combo.isEnabled() is False
    assert widget.quantity_input.isEnabled() is False
    assert widget.findChild(QPushButton, "addPalletAllocationButton").isEnabled() is False
    assert widget.findChild(QPushButton, "removePalletAllocationButton").isEnabled() is False

    widget.add_pallet()
    app.processEvents()

    assert widget.findChild(QLabel, "palletCompositionEmptyState") is None
    assert widget.findChild(QPushButton, "addPalletCardButton").text() == "+ Agregar pallet"
    assert widget.destination_combo.isEnabled() is True
    assert widget.quantity_input.isEnabled() is True


def test_pallet_cards_show_large_live_kilos_and_completion_state(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.add_allocation(1, destinations[0]["address_id"], destinations[0]["products"][0]["product_id"], 40)
    widget.add_pallet()
    widget.add_allocation(2, destinations[1]["address_id"], destinations[1]["products"][0]["product_id"], 5)
    app.processEvents()

    assert widget.objectName() == "palletCompositionWidget"
    assert widget.total_kg_label.objectName() == "loadOrderTotalKg"
    assert widget.total_kg_label.text() == "1.050,000 kg"
    assert widget.card_for_sequence(1).property("compositionState") == "complete"
    assert widget.card_for_sequence(2).property("compositionState") == "complete"
    assert widget.card_for_sequence(1).width() == widget.card_for_sequence(1).height()
    assert widget.summary_label.text() == "2 pallets · 2 completos · 0 pendientes"


def test_selected_product_suggests_pending_quantity_and_prevents_excess(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    destination = destinations[0]
    product = destination["products"][0]
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.destination_combo.setCurrentIndex(
        widget.destination_combo.findData(destination["address_id"])
    )
    widget.product_combo.setCurrentIndex(widget.product_combo.findData(product["product_id"]))
    app.processEvents()

    assert widget.quantity_input.value() == 40
    assert widget.quantity_input.maximum() == 40
    assert widget.quantity_input.isReadOnly() is False

    widget.quantity_input.setValue(10)
    widget._add_from_editor()
    app.processEvents()

    assert widget.quantity_input.value() == 30
    assert widget.quantity_input.maximum() == 30

    widget.add_pallet()
    app.processEvents()

    assert widget.quantity_input.value() == 30
    assert widget.quantity_input.maximum() == 30
    widget.quantity_input.setValue(999)
    assert widget.quantity_input.value() == 30
    widget._add_from_editor()
    app.processEvents()

    assert widget.quantity_input.value() == 0
    assert widget.quantity_input.maximum() == 0
    assert widget.add_allocation_button.isEnabled() is False
    assert widget.pallet_drafts()[0]["allocations"][0]["quantity"] == 10
    assert widget.pallet_drafts()[1]["allocations"][0]["quantity"] == 30


def test_pallet_widget_supports_mixed_clients_and_serializes_draft(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.add_allocation(1, destinations[0]["address_id"], destinations[0]["products"][0]["product_id"], 10)
    widget.add_allocation(1, destinations[1]["address_id"], destinations[1]["products"][0]["product_id"], 5)
    app.processEvents()

    draft = widget.pallet_drafts()
    assert len(draft) == 1
    assert len(draft[0]["allocations"]) == 2
    assert widget.card_for_sequence(1).client_count_label.text() == "2 clientes"
    assert widget.card_for_sequence(1).property("compositionState") == "incomplete"
    assert "300,000 kg" in widget.total_kg_label.text()


def test_pallet_cards_show_individual_invalid_and_complete_states(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.add_allocation(1, destinations[0]["address_id"], destinations[0]["products"][0]["product_id"], 41)
    widget.add_pallet()
    widget.add_allocation(2, destinations[1]["address_id"], destinations[1]["products"][0]["product_id"], 5)
    app.processEvents()

    assert widget.card_for_sequence(1).property("compositionState") == "invalid"
    assert widget.card_for_sequence(2).property("compositionState") == "complete"
    assert widget.summary_label.text() == "2 pallets · 1 completo · 1 pendiente"


def test_zero_weight_marks_only_the_pallet_with_that_snapshot(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    destination = destinations[0]
    product = destination["products"][0]
    widget = PalletCompositionWidget(destinations=destinations)
    widget.load_pallets(
        [
            {
                "sequence": 1,
                "allocations": [{
                    "client_id": destination["client_id"],
                    "address_id": destination["address_id"],
                    "product_id": product["product_id"],
                    "quantity": 20,
                    "peso_unitario_kg": Decimal("0.000"),
                }],
            },
            {
                "sequence": 2,
                "allocations": [{
                    "client_id": destination["client_id"],
                    "address_id": destination["address_id"],
                    "product_id": product["product_id"],
                    "quantity": 20,
                    "peso_unitario_kg": Decimal("25.000"),
                }],
            },
        ]
    )
    app.processEvents()

    assert widget.card_for_sequence(1).property("compositionState") == "incomplete"
    assert widget.card_for_sequence(2).property("compositionState") == "complete"

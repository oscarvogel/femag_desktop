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

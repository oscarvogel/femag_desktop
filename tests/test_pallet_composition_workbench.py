import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _destinations(db):
    from app.models.masters import Client, ClientAddress, Product

    client = Client.create(
        name="Cliente workbench pallet",
        cuit="30700000401",
        iva_condition="RI",
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino workbench",
    )
    product = Product.create(
        name="Fecula Nativa x 25 kg",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    return [
        {
            "client_id": client.id,
            "address_id": address.id,
            "client_label": client.name,
            "address_label": address.address,
            "products": [
                {
                    "product_id": product.id,
                    "product_label": product.name,
                    "quantity": 60,
                    "unit": product.unit,
                }
            ],
        }
    ]


def test_pending_merchandise_is_visible_while_pallets_are_visible(db):
    from PyQt5.QtWidgets import QApplication, QFrame

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    app.processEvents()

    workbench = widget.findChild(QFrame, "palletPendingWorkbench")
    assert workbench is not None
    assert widget.editor_tabs.isAncestorOf(workbench) is False
    assert widget.pending_table.rowCount() == 1
    assert widget.pending_table.item(0, 3).text() == "60"
    assert widget.pending_table.item(0, 4).text() == "0"
    assert widget.pending_table.item(0, 6).text() == "60"

    widget.add_pallet()
    widget.add_allocation(
        1,
        destinations[0]["address_id"],
        destinations[0]["products"][0]["product_id"],
        10,
    )
    app.processEvents()

    assert widget.pending_table.item(0, 4).text() == "10"
    assert widget.pending_table.item(0, 6).text() == "50"


def test_pallet_card_exposes_real_product_composition(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.add_allocation(
        1,
        destinations[0]["address_id"],
        destinations[0]["products"][0]["product_id"],
        12,
    )
    app.processEvents()

    card = widget.card_for_sequence(1)
    assert "12 x Fecula Nativa x 25 kg" in card.article_count_label.text()
    assert "Fecula Nativa x 25 kg" in card.article_count_label.toolTip()

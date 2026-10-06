import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _destinations(db, *, quantity=60, weight=Decimal("25.000")):
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
        peso_unitario_kg=weight,
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
                    "quantity": quantity,
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


def test_guided_manual_add_creates_current_pallet_and_moves_pending_line(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    destinations = _destinations(db, quantity=60)
    widget = PalletCompositionWidget(destinations=destinations)
    app.processEvents()

    widget.pending_table.selectRow(0)
    assert widget.add_selected_to_current_pallet() is True
    app.processEvents()

    drafts = widget.pallet_drafts()
    assert len(drafts) == 1
    assert Decimal(str(drafts[0]["allocations"][0]["quantity"])) == Decimal("60")
    assert widget.pending_table.rowCount() == 0
    assert widget.guided_content_table.rowCount() == 1


def test_guided_auto_distribution_creates_60_60_30_for_150_bags(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    destinations = _destinations(db, quantity=150, weight=Decimal("25"))
    widget = PalletCompositionWidget(destinations=destinations)
    app.processEvents()

    widget.pending_table.selectRow(0)
    assert widget.distribute_selected_automatically() is True
    app.processEvents()

    drafts = widget.pallet_drafts()
    assert len(drafts) == 3
    quantities = [
        Decimal(str(pallet["allocations"][0]["quantity"]))
        for pallet in drafts
    ]
    assert quantities == [Decimal("60"), Decimal("60"), Decimal("30")]
    kilos = [
        quantity * Decimal("25")
        for quantity in quantities
    ]
    assert kilos == [Decimal("1500"), Decimal("1500"), Decimal("750")]
    assert widget.pending_table.rowCount() == 0


def test_guided_auto_distribution_does_not_reuse_loaded_pallet(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    destinations = _destinations(db, quantity=150, weight=Decimal("25"))
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallet()
    widget.add_allocation(
        1,
        destinations[0]["address_id"],
        destinations[0]["products"][0]["product_id"],
        10,
    )
    app.processEvents()

    widget.pending_table.selectRow(0)
    assert widget.distribute_selected_automatically() is True
    drafts = widget.pallet_drafts()

    assert Decimal(str(drafts[0]["allocations"][0]["quantity"])) == Decimal("10")
    auto_quantities = [
        Decimal(str(pallet["allocations"][0]["quantity"]))
        for pallet in drafts[1:]
    ]
    assert auto_quantities == [Decimal("60"), Decimal("60"), Decimal("20")]

from decimal import Decimal


def _destinations(db):
    from app.models.masters import Client, ClientAddress, Product

    client = Client.create(name="Cliente auto pallets", cuit="30700000981", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito auto",
    )
    product = Product.create(
        name="Fecula auto 25 kg",
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


def test_auto_proposal_is_preview_until_operator_accepts(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.add_pallets(2)

    assert all(not pallet["allocations"] for pallet in widget.pallet_drafts())
    widget.propose_distribution_button.click()
    app.processEvents()

    assert widget.proposal_table.rowCount() == 2
    assert all(not pallet["allocations"] for pallet in widget.pallet_drafts())
    assert widget.accept_proposal_button.isEnabled() is True

    widget.accept_proposal_button.click()
    app.processEvents()

    assert sum(len(pallet["allocations"]) for pallet in widget.pallet_drafts()) > 0
    assert all(
        sum(
            Decimal(str(allocation["quantity"])) * Decimal(str(allocation["peso_unitario_kg"]))
            for allocation in pallet["allocations"]
        ) <= Decimal("1000")
        for pallet in widget.pallet_drafts()
    )


def test_lock_pallet_is_visible_and_reorganize_preserves_it(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(2)
    product = destinations[0]["products"][0]
    widget.add_allocation(1, destinations[0]["address_id"], product["product_id"], 20)
    widget._select_pallet(1)
    widget.lock_pallet_button.click()
    app.processEvents()

    assert widget.pallet_drafts()[0]["locked"] is True
    assert "Fijado" in widget.card_for_sequence(1).status_label.text()

    before = [dict(item) for item in widget.pallet_drafts()[0]["allocations"]]
    widget.reorganize_pending_button.click()
    app.processEvents()
    assert widget.accept_proposal_button.isEnabled() is True
    widget.accept_proposal_button.click()
    app.processEvents()

    assert widget.pallet_drafts()[0]["locked"] is True
    assert widget.pallet_drafts()[0]["allocations"] == before


def test_pending_grid_replaces_operator_need_for_text_only_summary(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.add_pallets(2)
    app.processEvents()

    assert widget.pending_table.rowCount() == 1
    assert widget.pending_table.item(0, 3).text() == "60"
    assert widget.pending_table.item(0, 6).text() == "60"
    assert widget.pending_table.item(0, 7).text() == "1.500 kg"


def test_truck_capacity_is_inherited_from_container_order_and_shows_margin(db):
    from types import SimpleNamespace

    from PyQt5.QtWidgets import QApplication, QWidget

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    host = QWidget()
    host.order = SimpleNamespace(
        truck=SimpleNamespace(max_load_kg=Decimal("1200.000"))
    )
    widget = PalletCompositionWidget(destinations=destinations, parent=host)
    widget.add_pallets(2)
    product = destinations[0]["products"][0]
    widget.add_allocation(1, destinations[0]["address_id"], product["product_id"], 40)
    widget.show()
    app.processEvents()

    assert widget._truck_max_load_kg == Decimal("1200.000")
    assert "Camion: 1.000 kg / 1.200 kg" in widget.capacity_summary_label.text()
    assert "margen 200 kg" in widget.capacity_summary_label.text()


def test_truck_capacity_excess_is_prominent_and_includes_loose_goods(db):
    from types import SimpleNamespace

    from PyQt5.QtWidgets import QApplication, QWidget

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    host = QWidget()
    host.order = SimpleNamespace(
        truck=SimpleNamespace(max_load_kg=Decimal("1200.000"))
    )
    widget = PalletCompositionWidget(destinations=destinations, parent=host)
    widget.add_pallets(2)
    product = destinations[0]["products"][0]
    address_id = destinations[0]["address_id"]
    widget.add_allocation(1, address_id, product["product_id"], 40)
    widget.add_loose_allocation(address_id, product["product_id"], 20)
    widget.show()
    app.processEvents()

    assert "Camion: 1.500 kg / 1.200 kg" in widget.capacity_summary_label.text()
    assert "EXCEDIDO por 300 kg" in widget.capacity_summary_label.text()
    assert "#b53b3b" in widget.capacity_summary_label.styleSheet()


def test_permanent_summary_tracks_assigned_loose_and_pending(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(2)
    product = destinations[0]["products"][0]
    address_id = destinations[0]["address_id"]
    widget.add_allocation(1, address_id, product["product_id"], 20)
    widget.add_loose_allocation(address_id, product["product_id"], 10)
    app.processEvents()

    summary = widget.order_flow_summary_label.text()
    assert "Pedido: 60" in summary
    assert "En pallets: 20" in summary
    assert "Suelto: 10" in summary
    assert "Pendiente: 30" in summary
    assert "Pallets: 2" in summary


def test_pending_grid_can_filter_by_client_destination_or_product(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.add_pallets(1)

    widget.pending_filter_input.setText("fecula auto")
    app.processEvents()
    assert widget.pending_table.rowCount() == 1

    widget.pending_filter_input.setText("cliente inexistente")
    app.processEvents()
    assert widget.pending_table.rowCount() == 0

    widget.pending_filter_input.clear()
    app.processEvents()
    assert widget.pending_table.rowCount() == 1


def test_recalculate_all_requires_confirmation_and_only_builds_preview(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(2)
    product = destinations[0]["products"][0]
    widget.add_allocation(1, destinations[0]["address_id"], product["product_id"], 20)
    widget._select_pallet(1)
    widget.lock_pallet_button.click()
    before = widget.pallet_drafts()

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    widget.recalculate_all_button.click()
    app.processEvents()
    assert widget._prepared_proposal is None
    assert widget.pallet_drafts() == before

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    widget.recalculate_all_button.click()
    app.processEvents()
    assert widget._prepared_proposal is not None
    assert widget.pallet_drafts() == before
    assert all(pallet.locked is False for pallet in widget._prepared_proposal.proposal.pallets)


def test_pallet_over_global_max_is_marked_as_exceeded(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(1)
    product = destinations[0]["products"][0]
    widget.add_allocation(1, destinations[0]["address_id"], product["product_id"], 50)
    app.processEvents()

    card = widget.card_for_sequence(1)
    assert "EXCEDIDO" in card.status_label.text()
    assert "max 1.000 kg" in card.status_label.text()
    assert card.property("compositionState") == "invalid"

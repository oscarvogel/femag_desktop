import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _destinations(db, *, quantity=1500, weight=Decimal("1.000")):
    from app.models.masters import Client, ClientAddress, Product

    client = Client.create(
        name="Cliente UX pallets",
        cuit="30700000451",
        iva_condition="RI",
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino UX pallets",
    )
    product = Product.create(
        name="Fecula de mandioca",
        unit="unidad",
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


def test_guided_selector_shows_twenty_clickable_pallets_without_combo(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.guided_total_pallets_input.setValue(20)
    widget._guided_create_to_total()
    app.processEvents()

    assert len(widget.pallet_drafts()) == 20
    assert widget.guided_pallet_combo.isHidden() is True
    assert len(widget._guided_pallet_buttons) == 20

    pallet_17 = widget.findChild(QPushButton, "guidedPalletSelectorButton_17")
    assert pallet_17 is not None
    pallet_17.click()
    app.processEvents()

    assert widget._selected_sequence == 17
    assert widget._guided_pallet_buttons[17].isChecked() is True
    assert "PALLET ACTUAL: 17" == widget.guided_current_pallet_label.text()
    assert "Pallet 17" in widget.guided_totals_label.text()
    assert "background: #173a59" in widget._guided_pallet_buttons[17].styleSheet()


def test_guided_capacity_action_is_visible_when_workbench_is_shown(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.system import AppParameter
    from app.services.pallet_capacity_service import PALLET_MAX_KG_KEY
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    AppParameter.delete().where(AppParameter.key == PALLET_MAX_KG_KEY).execute()
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.show()
    app.processEvents()

    assert "SIN CONFIGURAR" in widget.guided_capacity_label.text()
    assert widget.guided_configure_capacity_button.isVisible() is True
    assert widget.guided_configure_capacity_button.text() == "Configurar Kg/pallet"
    assert widget.guided_configure_capacity_button.width() >= 120


def test_guided_actions_explain_missing_pallet_capacity_in_visible_feedback(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.system import AppParameter
    from app.services.pallet_capacity_service import PALLET_MAX_KG_KEY
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    AppParameter.delete().where(AppParameter.key == PALLET_MAX_KG_KEY).execute()
    widget = PalletCompositionWidget(destinations=_destinations(db))
    app.processEvents()

    assert "SIN CONFIGURAR" in widget.guided_capacity_label.text()
    widget.pending_table.selectRow(0)
    assert widget.add_selected_to_current_pallet() is False
    app.processEvents()

    assert widget.issue_label.kind == "warning"
    assert "Configure Kg/pallet" in widget.issue_label.message
    assert widget.issue_label.isHidden() is False

    assert widget.propose_remainder() is False
    assert "Configure Kg/pallet" in widget.issue_label.message


def test_guided_manual_add_works_from_visible_flow_when_capacity_is_configured(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.guided_total_pallets_input.setValue(19)
    widget._guided_create_to_total()
    app.processEvents()

    widget.pending_table.selectRow(0)
    assert widget.add_selected_to_current_pallet() is True
    app.processEvents()

    first = widget.pallet_drafts()[0]
    assert Decimal(str(first["allocations"][0]["quantity"])) == Decimal("1500")
    assert widget.pending_table.rowCount() == 0
    assert "1.500 kg" in widget.guided_totals_label.text()


def test_guided_delete_empty_pallet_renumbers_and_keeps_selection_clear(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    widget = PalletCompositionWidget(destinations=_destinations(db))
    widget.guided_total_pallets_input.setValue(5)
    widget._guided_create_to_total()
    widget._guided_select_pallet(3)
    app.processEvents()

    widget._guided_delete_current_pallet()
    app.processEvents()

    assert [pallet["sequence"] for pallet in widget.pallet_drafts()] == [1, 2, 3, 4]
    assert widget._selected_sequence == 3
    assert widget.guided_current_pallet_label.text() == "PALLET ACTUAL: 3"
    assert len(widget._guided_pallet_buttons) == 4


def test_guided_delete_loaded_pallet_returns_merchandise_to_pending(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1500"))
    destinations = _destinations(db, quantity=100, weight=Decimal("1"))
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(2)
    widget.add_allocation(
        1,
        destinations[0]["address_id"],
        destinations[0]["products"][0]["product_id"],
        40,
    )
    widget._guided_select_pallet(1)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    app.processEvents()

    widget._guided_delete_current_pallet()
    app.processEvents()

    assert len(widget.pallet_drafts()) == 1
    assert widget.pallet_drafts()[0]["sequence"] == 1
    assert widget.pending_table.rowCount() == 1
    assert widget.pending_table.item(0, 6).text() == "100"


def test_guided_partial_action_is_visible_and_usable(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    widget = PalletCompositionWidget(destinations=_destinations(db, quantity=1000, weight=Decimal("1")))
    widget.show()
    app.processEvents()

    assert widget.guided_partial_button.isVisible() is True
    assert widget.guided_partial_button.text() == "Agregar cantidad..."
    assert widget.guided_partial_button.width() >= 140


def test_guided_partial_flow_splits_300_600_100_across_three_pallets(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QInputDialog

    from app.services.pallet_capacity_service import PalletCapacityService
    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    PalletCapacityService.set_pallet_max_kg(Decimal("1000"))
    widget = PalletCompositionWidget(destinations=_destinations(db, quantity=1000, weight=Decimal("1")))
    widget.guided_total_pallets_input.setValue(3)
    widget._guided_create_to_total()
    app.processEvents()

    values = iter((300.0, 600.0, 100.0))
    monkeypatch.setattr(
        QInputDialog,
        "getDouble",
        lambda *args, **kwargs: (next(values), True),
    )

    for sequence, expected_pending in ((1, "700"), (2, "100"), (3, None)):
        widget._guided_select_pallet(sequence)
        widget.pending_table.selectRow(0)
        assert widget.add_selected_partial() is True
        app.processEvents()
        if expected_pending is None:
            assert widget.pending_table.rowCount() == 0
        else:
            assert widget.pending_table.item(0, 6).text() == expected_pending

    drafts = widget.pallet_drafts()
    quantities = [Decimal(str(pallet["allocations"][0]["quantity"])) for pallet in drafts]
    assert quantities == [Decimal("300"), Decimal("600"), Decimal("100")]

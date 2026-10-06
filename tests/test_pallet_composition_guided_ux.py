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
    assert "Pallet 17" in widget.guided_totals_label.text()


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

from decimal import Decimal


_APP = None


def _application():
    from PyQt5.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _new_dialog(db, current_user="ui_798"):
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    _master_data()
    app = _application()
    dialog = RemittanceDialog(current_user=current_user)
    app.processEvents()
    return dialog


def test_new_remittance_shows_zero_total_and_subtotal_column(db):
    dialog = _new_dialog(db)

    assert dialog.total_title_label.text() == "TOTAL GENERAL"
    assert dialog.total_value_label.text() == "$ 0.00"
    assert "font-size: 24px" in dialog.total_value_label.styleSheet()
    assert dialog.items.columnCount() == 5
    assert dialog.items.horizontalHeaderItem(4).text() == "Subtotal"
    assert dialog.items.item(0, 4).text() == "$ 0.00"


def test_total_updates_when_quantity_price_and_rows_change(db):
    dialog = _new_dialog(db)
    quantity = dialog.items.cellWidget(0, 1)
    price = dialog.items.cellWidget(0, 2)

    quantity.setText("2")
    price.setText("1500.00")
    assert dialog.items.item(0, 4).text() == "$ 3,000.00"
    assert dialog.total_value_label.text() == "$ 3,000.00"

    dialog._add_item_row()
    dialog.items.cellWidget(1, 1).setText("3")
    dialog.items.cellWidget(1, 2).setText("2000.00")
    assert dialog.items.item(1, 4).text() == "$ 6,000.00"
    assert dialog.total_value_label.text() == "$ 9,000.00"

    quantity.setText("4")
    assert dialog.total_value_label.text() == "$ 12,000.00"

    dialog.items.cellWidget(1, 2).setText("2500.00")
    assert dialog.total_value_label.text() == "$ 13,500.00"

    dialog.items.removeRow(1)
    assert dialog.total_value_label.text() == "$ 6,000.00"


def test_total_uses_system_decimal_rounding(db):
    dialog = _new_dialog(db)

    dialog.items.cellWidget(0, 1).setText("1.005")
    dialog.items.cellWidget(0, 2).setText("1.00")

    assert dialog.items.item(0, 4).text() == "$ 1.01"
    assert dialog.total_value_label.text() == "$ 1.01"


def test_incomplete_line_is_marked_without_showing_a_misleading_total(db):
    dialog = _new_dialog(db)

    dialog.items.cellWidget(0, 1).setText("2")

    assert dialog.items.item(0, 4).text() == "Revisar"
    assert dialog.total_value_label.text() == "$ —"
    assert dialog.total_hint_label.isVisibleTo(dialog)
    assert "incompletos" in dialog.total_hint_label.text()

    dialog.items.cellWidget(0, 2).setText("1500.00")

    assert not dialog.total_hint_label.isVisible()
    assert dialog.total_value_label.text() == "$ 3,000.00"


def test_opening_a_draft_calculates_the_total_and_subtotals(db):
    from datetime import date

    from app.models.masters import Client, ClientAddress, Product
    from app.services.remittance_service import RemittanceService
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    data = _master_data()
    client = Client.create(name="Cliente Total", cuit="30712345888", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    first = Product.create(name="Producto Total A", unit="kg")
    second = Product.create(name="Producto Total B", unit="kg")
    remittance = RemittanceService("ui_798_draft").create_manual(
        client=client,
        delivery_address=address,
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        physical_point_of_sale="0001",
        physical_number="7980",
        remittance_date=date(2026, 10, 27),
        items=[
            {"product": first, "quantity": Decimal("2"), "unit_price": Decimal("1500")},
            {"product": second, "quantity": Decimal("3"), "unit_price": Decimal("2000")},
        ],
    )
    app = _application()
    dialog = RemittanceDialog(current_user="ui_798_draft", remittance=remittance)
    app.processEvents()

    assert dialog.items.item(0, 4).text() == "$ 3,000.00"
    assert dialog.items.item(1, 4).text() == "$ 6,000.00"
    assert dialog.total_value_label.text() == "$ 9,000.00"

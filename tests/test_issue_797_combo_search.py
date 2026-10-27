from decimal import Decimal


_APP = None


def _application():
    from PyQt5.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _searchable_combo():
    from app.ui.combo_autocomplete import SEARCH_COLUMNS_ROLE, SearchableComboBox

    _application()
    combo = SearchableComboBox(
        placeholder="Buscar chofer...",
        search_headers=("Chofer", "Documento"),
    )
    for label, value, document in (("Alfa", 1, "10"), ("Beta", 2, "20"), ("Zulu", 3, "30")):
        combo.addItem(label, value)
        combo.setItemData(
            combo.count() - 1, (label, document), SEARCH_COLUMNS_ROLE
        )
    return combo


def test_new_searchable_combo_can_show_placeholder_without_selection():
    combo = _searchable_combo()

    combo.setCurrentIndex(-1)

    assert combo.currentIndex() == -1
    assert combo.currentData() is None
    assert combo.lineEdit().placeholderText() == "Buscar chofer..."


def test_click_selects_the_text_and_typing_does_not_expose_the_old_id():
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    app = _application()
    combo = _searchable_combo()
    combo.setCurrentIndex(1)
    combo.show()
    app.processEvents()

    QTest.mouseClick(combo.lineEdit(), Qt.LeftButton)
    QTest.qWait(10)

    assert combo.lineEdit().selectedText() == "Beta"

    QTest.keyClicks(combo.lineEdit(), "Al")

    assert combo.lineEdit().text() == "Al"
    assert combo.currentIndex() == 1
    assert combo.currentData() is None


def test_unconfirmed_search_text_restores_the_committed_value():
    combo = _searchable_combo()
    combo.setCurrentIndex(1)

    combo.setEditText("cliente inventado")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentIndex() == 1
    assert combo.currentText() == "Beta"
    assert combo.currentData() == 2


def test_exact_typed_text_commits_the_selected_item():
    combo = _searchable_combo()
    combo.setCurrentIndex(1)

    combo.setEditText("alfa")
    combo.lineEdit().editingFinished.emit()

    assert combo.currentIndex() == 0
    assert combo.currentText() == "Alfa"
    assert combo.currentData() == 1


def test_f2_dialog_sorts_filters_and_accepts_with_enter():
    from app.ui.combo_autocomplete import SEARCH_COLUMNS_ROLE, ComboSearchDialog

    combo = _searchable_combo()
    combo.addItem("Ávila", 4)
    combo.setItemData(combo.count() - 1, ("Ávila", "40"), SEARCH_COLUMNS_ROLE)
    combo.setCurrentIndex(1)

    dialog = ComboSearchDialog(combo)

    assert [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())] == [
        "Alfa",
        "Ávila",
        "Beta",
        "Zulu",
    ]

    dialog.search_input.setText("avi")

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "Ávila"
    assert dialog.table.item(0, 1).text() == "40"

    dialog.table.selectRow(0)
    dialog._accept_current()

    assert dialog.selected_index == 3


def test_f2_cancel_does_not_change_the_committed_value(db, monkeypatch):
    from PyQt5.QtWidgets import QDialog

    from app.ui import combo_autocomplete
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    data = _master_data()
    app = _application()
    dialog = RemittanceDialog(current_user="ui_797_cancel")
    app.processEvents()
    dialog.driver_combo.setCurrentIndex(dialog.driver_combo.findData(data["driver"].id))
    committed_text = dialog.driver_combo.currentText()
    dialog.driver_combo.setEditText("otro chofer")
    monkeypatch.setattr(combo_autocomplete.ComboSearchDialog, "exec_", lambda _self: QDialog.Rejected)

    dialog.driver_combo.open_search_dialog()

    assert dialog.driver_combo.currentData() == data["driver"].id
    assert dialog.driver_combo.currentText() == committed_text


def test_new_remittance_combos_start_without_arbitrary_values(db):
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    _master_data()
    app = _application()
    dialog = RemittanceDialog(current_user="ui_797_new_remito")
    app.processEvents()

    for combo in (
        dialog.client_combo,
        dialog.address_combo,
        dialog.driver_combo,
        dialog.carrier_combo,
        dialog.truck_combo,
        dialog.items.cellWidget(0, 0),
    ):
        assert combo.currentIndex() == -1
        assert combo.currentData() is None


def test_new_load_order_combos_start_without_arbitrary_values(db):
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog
    from tests.conftest import _master_data

    _master_data()
    app = _application()
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_797_new_order"), "ui_797_new_order")
    app.processEvents()

    for combo in (
        dialog.driver_combo,
        dialog.carrier_combo,
        dialog.truck_combo,
        dialog.trailer_combo,
        dialog.client_combo,
        dialog.address_combo,
    ):
        assert combo.currentData() is None
        assert combo.currentText() == ""


def test_remittance_f2_driver_selection_cascades_the_transport(db, monkeypatch):
    from PyQt5.QtWidgets import QDialog

    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Carrier, Driver, Truck
    from app.ui import combo_autocomplete
    from app.ui.remittances import RemittanceDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte F2", cuit="30777779797")
    truck = Truck.create(domain="F2A111", trailer_domain="F2B222", carrier=carrier)
    driver = Driver.create(name="Chofer F2", carrier=carrier, usual_truck=truck, document="30111222")
    dialog = RemittanceDialog(current_user="ui_797_f2")
    app.processEvents()

    def accept_driver(search_dialog):
        index = search_dialog.combo.findData(driver.id)
        for row, (_columns, combo_index) in enumerate(search_dialog._rows):
            if combo_index == index:
                search_dialog.table.selectRow(row)
                break
        search_dialog._accept_current()
        return QDialog.Accepted

    monkeypatch.setattr(combo_autocomplete.ComboSearchDialog, "exec_", accept_driver)

    dialog.driver_combo.open_search_dialog()
    app.processEvents()

    assert dialog.driver_combo.currentData() == driver.id
    assert dialog.carrier_combo.currentData() == carrier.id
    assert dialog.truck_combo.currentData() == truck.id
    assert dialog.trailer_input.text() == "F2B222"


def test_load_order_f2_driver_selection_cascades_the_transport(db, monkeypatch):
    from PyQt5.QtWidgets import QDialog, QApplication

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui import combo_autocomplete
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte F2 Orden", cuit="30777779696")
    truck = Truck.create(domain="F2C333", trailer_domain="F2D444", carrier=carrier)
    driver = Driver.create(name="Chofer F2 Orden", carrier=carrier, usual_truck=truck, document="30111333")
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_797_f2_order"), "ui_797_f2_order")
    app.processEvents()

    def accept_driver(search_dialog):
        index = search_dialog.combo.findData(driver.id)
        for row, (_columns, combo_index) in enumerate(search_dialog._rows):
            if combo_index == index:
                search_dialog.table.selectRow(row)
                break
        search_dialog._accept_current()
        return QDialog.Accepted

    monkeypatch.setattr(combo_autocomplete.ComboSearchDialog, "exec_", accept_driver)

    dialog.driver_combo.open_search_dialog()
    app.processEvents()

    assert dialog.driver_combo.currentData() == driver.id
    assert dialog.carrier_combo.currentData() == carrier.id
    assert dialog.truck_combo.currentData() == truck.id
    assert dialog.trailer_combo.currentData() == "F2D444"


def test_editing_a_draft_keeps_saved_ids_when_search_text_is_not_confirmed(db):
    from datetime import date

    from app.models.masters import Client, ClientAddress, Product
    from app.services.remittance_service import RemittanceService
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    data = _master_data()
    client = Client.create(name="Cliente Borrador F2", cuit="30712345777", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 8",
        is_primary=True,
    )
    product = Product.create(name="Producto Borrador F2", unit="kg")
    remittance = RemittanceService("ui_797_draft").create_manual(
        client=client,
        delivery_address=address,
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        physical_point_of_sale="0001",
        physical_number="7970",
        remittance_date=date(2026, 10, 27),
        items=[{"product": product, "quantity": Decimal("2"), "unit_price": Decimal("10")}],
    )
    app = _application()
    dialog = RemittanceDialog(current_user="ui_797_draft", remittance=remittance)
    app.processEvents()
    saved_text = dialog.driver_combo.currentText()

    dialog.driver_combo.setEditText("chofer que no existe")
    dialog.driver_combo.lineEdit().editingFinished.emit()

    assert dialog.driver_combo.currentData() == data["driver"].id
    assert dialog.driver_combo.currentText() == saved_text
    assert dialog.carrier_combo.currentData() == data["carrier"].id
    assert dialog.truck_combo.currentData() == data["truck"].id

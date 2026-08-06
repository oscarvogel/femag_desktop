import os
from decimal import Decimal

import pytest

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


def test_kg_text_hides_zero_decimals_and_keeps_real_precision():
    from app.ui.pallet_composition import _kg_text

    assert _kg_text(200) == "200 kg"
    assert _kg_text(Decimal("200.500")) == "200,5 kg"
    assert _kg_text(Decimal("1234.125")) == "1.234,125 kg"


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
    assert widget.findChild(QPushButton, "removePalletProductButton_0") is None

    widget.add_pallet()
    app.processEvents()

    assert widget.findChild(QLabel, "palletCompositionEmptyState") is None
    assert widget.findChild(QPushButton, "addPalletCardButton").text() == "+ Agregar pallet"
    assert widget.destination_combo.isEnabled() is True
    assert widget.quantity_input.isEnabled() is True


def test_pallet_card_stylesheet_does_not_emit_qt_parse_warnings():
    from PyQt5.QtCore import qInstallMessageHandler
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCard

    app = QApplication.instance() or QApplication([])
    messages = []

    def capture_message(_message_type, _context, message):
        messages.append(message)

    previous_handler = qInstallMessageHandler(capture_message)
    try:
        card = PalletCard(1)
        card.show()
        for state in ("complete", "incomplete", "invalid"):
            card.set_state(state)
            card.repaint()
            app.processEvents()
        card.close()
    finally:
        qInstallMessageHandler(previous_handler)

    assert not [message for message in messages if "Could not parse stylesheet" in message]


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
    assert widget.total_kg_label.text() == "1.050 kg"
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


def test_assigned_product_has_its_own_remove_button(db):
    from PyQt5.QtWidgets import QApplication, QAbstractItemView, QPushButton

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
    widget.quantity_input.setValue(10)
    widget._add_from_editor()
    app.processEvents()

    assert widget.allocation_table.selectionBehavior() == QAbstractItemView.SelectRows
    assert widget.allocation_table.currentRow() == 0
    remove_button = widget.findChild(QPushButton, "removePalletProductButton_0")
    assert remove_button is not None
    assert remove_button.text() == "Quitar"
    assert remove_button.isEnabled() is True

    remove_button.click()
    app.processEvents()

    assert widget.pallet_drafts()[0]["allocations"] == []
    assert widget.quantity_input.value() == 40
    assert widget.allocation_table.rowCount() == 0


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
    assert "300 kg" in widget.total_kg_label.text()


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


def test_add_pallets_in_bulk_creates_consecutive_cards_with_one_change_signal(db):
    from PyQt5.QtTest import QSignalSpy
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    widget = PalletCompositionWidget(destinations=_destinations(db))
    spy = QSignalSpy(widget.composition_changed)

    widget.bulk_pallet_count_input.setValue(19)
    widget.add_pallet_button.click()
    app.processEvents()

    assert [pallet["sequence"] for pallet in widget.pallet_drafts()] == list(range(1, 20))
    assert widget.card_for_sequence(19).title_label.text() == "PALLET 19"
    assert widget.summary_label.text().startswith("19 pallets")
    assert len(spy) == 1

    widget.bulk_pallet_count_input.setValue(3)
    widget.add_pallet_button.click()
    app.processEvents()

    assert [pallet["sequence"] for pallet in widget.pallet_drafts()][-3:] == [20, 21, 22]
    assert len(spy) == 2


def test_bulk_assignment_applies_one_client_product_to_existing_pallets(db):
    from PyQt5.QtTest import QSignalSpy
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    destination = destinations[0]
    product = destination["products"][0]
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(19)
    widget.destination_combo.setCurrentIndex(
        widget.destination_combo.findData(destination["address_id"])
    )
    widget.product_combo.setCurrentIndex(widget.product_combo.findData(product["product_id"]))
    widget.bulk_start_input.setValue(1)
    widget.bulk_target_count_input.setValue(10)
    app.processEvents()

    assert widget.bulk_quantity_input.value() == 4
    assert "10 pallets x 4 = 40 unidades" in widget.bulk_preview_label.text()
    spy = QSignalSpy(widget.composition_changed)
    widget.bulk_assign_button.click()
    app.processEvents()

    drafts = widget.pallet_drafts()
    assert all(len(pallet["allocations"]) == 1 for pallet in drafts[:10])
    assert all(pallet["allocations"] == [] for pallet in drafts[10:])
    assert {
        allocation["client_id"]
        for pallet in drafts[:10]
        for allocation in pallet["allocations"]
    } == {destination["client_id"]}
    assert widget.total_kg_label.text() == "1.000 kg"
    assert len(spy) == 1


def test_bulk_assignment_rejects_excess_and_unknown_pallets(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    destination = destinations[0]
    product = destination["products"][0]
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(2)

    with pytest.raises(ValueError, match="supera la cantidad pendiente"):
        widget.add_allocations_bulk(
            [1, 2],
            destination["address_id"],
            product["product_id"],
            21,
        )
    with pytest.raises(ValueError, match="pallets inexistentes"):
        widget.add_allocations_bulk(
            [1, 3],
            destination["address_id"],
            product["product_id"],
            1,
        )


def test_clear_all_allocations_keeps_cards_and_requires_confirmation(db, monkeypatch):
    from PyQt5.QtTest import QSignalSpy
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)
    widget.add_pallets(3)
    widget.add_allocation(
        1,
        destinations[0]["address_id"],
        destinations[0]["products"][0]["product_id"],
        20,
    )
    widget.add_allocation(
        2,
        destinations[1]["address_id"],
        destinations[1]["products"][0]["product_id"],
        5,
    )
    original_sequences = [pallet["sequence"] for pallet in widget.pallet_drafts()]

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    widget.clear_assignments_button.click()
    assert sum(len(pallet["allocations"]) for pallet in widget.pallet_drafts()) == 2

    spy = QSignalSpy(widget.composition_changed)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    widget.clear_assignments_button.click()
    app.processEvents()

    assert [pallet["sequence"] for pallet in widget.pallet_drafts()] == original_sequences
    assert all(pallet["allocations"] == [] for pallet in widget.pallet_drafts())
    assert widget.total_kg_label.text() == "0 kg"
    assert "3 pallets" in widget.summary_label.text()
    assert "0 completos" in widget.summary_label.text()
    assert "3 pendientes" in widget.summary_label.text()
    assert widget.clear_assignments_button.isEnabled() is False
    assert len(spy) == 1


def test_composition_widget_fits_in_notebook_viewport(db):
    """La pantalla de composicion de pallets debe entrar en notebooks 1280x720.

    Reportado en issue #208: la pantalla quedaba fuera de pantalla en pantallas
    chicas porque las cards eran de tamano fijo (180x180), el editor pedia
    300px minimos, y el editor tenia todo el contenido apilado verticalmente.
    El fix combina tres cambios:
    - cards escalan entre 150 y 200 (siguen cuadradas)
    - editor envuelto en un QScrollArea vertical
    - contenido del editor distribuido en 3 tabs (Individual / Masiva / Asignaciones)
    """
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QDoubleSpinBox,
        QFrame,
        QScrollArea,
        QTabWidget,
        QTableWidget,
        QWidget,
    )

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    destinations = _destinations(db)
    widget = PalletCompositionWidget(destinations=destinations)

    # Forzar el viewport tipico de una notebook moderna
    widget.resize(1280, 720)
    app.processEvents()

    # El minimumSizeHint del widget debe caber en el viewport.
    # Si Qt necesita mas espacio del que la pantalla ofrece, el widget
    # se recorta o aparecen scrolls no deseados.
    min_size = widget.minimumSizeHint()
    assert min_size.width() <= 1280, (
        f"El widget pide {min_size.width()}px de ancho pero la pantalla solo tiene 1280"
    )
    assert min_size.height() <= 720, (
        f"El widget pide {min_size.height()}px de alto pero la pantalla solo tiene 720"
    )

    # El editor panel debe respetar un minimo razonable (no menos de 240)
    assert widget.editor_panel.minimumWidth() == 240

    # El editor debe estar envuelto en un QScrollArea vertical para
    # que cuando la pantalla sea muy chica el contenido scrollee en vez
    # de cortarse.
    editor_scroll = widget.findChild(QScrollArea, "palletEditorScroll")
    assert editor_scroll is not None, "El editor no esta envuelto en un QScrollArea"
    assert editor_scroll.widgetResizable() is True
    # Sin scroll horizontal (solo vertical) para no romper el layout lado a lado
    assert editor_scroll.horizontalScrollBarPolicy() == 1  # Qt.ScrollBarAlwaysOff

    # El editor debe distribuir su contenido en 3 tabs (Individual / Masiva / Asignaciones)
    # para que el alto total entre en notebooks chicas.
    editor_tabs = widget.findChild(QTabWidget, "palletEditorTabs")
    assert editor_tabs is not None, "El editor no tiene un QTabWidget"
    assert editor_tabs.count() == 3, (
        f"Se esperaban 3 tabs (Individual / Masiva / Asignaciones) pero hay {editor_tabs.count()}"
    )
    tab_labels = [editor_tabs.tabText(i) for i in range(editor_tabs.count())]
    assert tab_labels == ["Individual", "Masiva", "Asignaciones"], (
        f"Labels de tabs inesperados: {tab_labels}"
    )

    # Verificar que la tab Individual contiene los widgets de asignacion individual
    tab_individual = widget.findChild(QWidget, "palletEditorTabIndividual")
    assert tab_individual is not None
    destination_combo = tab_individual.findChild(QComboBox, "palletDestinationInput")
    product_combo = tab_individual.findChild(QComboBox, "palletProductInput")
    assert destination_combo is not None
    assert product_combo is not None
    assert destination_combo.isEditable()
    assert destination_combo.completer().filterMode() == Qt.MatchContains
    assert product_combo.isEditable()
    assert tab_individual.findChild(QDoubleSpinBox, "palletAllocationQuantityInput") is not None

    # Verificar que la tab Masiva contiene el panel de bulk assignment
    tab_masiva = widget.findChild(QWidget, "palletEditorTabBulk")
    assert tab_masiva is not None
    assert tab_masiva.findChild(QFrame, "bulkPalletAssignmentPanel") is not None

    # Verificar que la tab Asignaciones contiene la tabla
    tab_asignaciones = widget.findChild(QWidget, "palletEditorTabAllocations")
    assert tab_asignaciones is not None
    assert tab_asignaciones.findChild(QTableWidget, "palletAllocationTable") is not None

    # Caso realista: 10 pallets como los que genera la operacion bulk.
    # Las cards deben escalar al rango 150-200 y seguir siendo cuadradas.
    widget.add_pallets(10)
    app.processEvents()
    widget.resize(1280, 720)
    app.processEvents()

    for sequence in range(1, 11):
        card = widget.card_for_sequence(sequence)
        assert 150 <= card.width() <= 200, (
            f"Card {sequence} tiene width={card.width()}, fuera del rango [150, 200]"
        )
        assert card.width() == card.height(), (
            f"Card {sequence} no es cuadrada ({card.width()}x{card.height()})"
        )

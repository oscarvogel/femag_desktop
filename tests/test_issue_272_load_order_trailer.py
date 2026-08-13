"""Tests de servicio, UI e impresión para #272: seleccionar e imprimir semi/acoplado."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import _master_data, _valid_order_payload


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0, f"Combo {combo.objectName()} no contiene {value!r}"
    combo.setCurrentIndex(index)


# ---------------------------------------------------------------------------
# Servicio
# ---------------------------------------------------------------------------


def test_create_load_order_persists_trailer_domain_snapshot(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()

    payload = _valid_order_payload(data)
    payload["trailer_domain"] = " acoplado-01 "

    order = LoadOrderService(current_user="admin").create_order(**payload)

    persisted = LoadOrder.get_by_id(order.id)
    assert persisted.trailer_domain == "ACOPLADO01"


def test_create_load_order_accepts_none_trailer_domain(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["trailer_domain"] = None

    order = LoadOrderService(current_user="admin").create_order(**payload)

    assert LoadOrder.get_by_id(order.id).trailer_domain is None


def test_create_load_order_rejects_trailer_outside_carrier(db):
    from app.models.masters import Carrier, Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_carrier = Carrier.create(name="Otro Transporte")
    other_truck = Truck.create(
        domain="OTROTRAILER",
        trailer_domain="EXTERN09",
        carrier=other_carrier,
    )
    payload = _valid_order_payload(data)
    payload["trailer_domain"] = "EXTERN09"

    with pytest.raises(ValueError, match="semi/acoplado"):
        LoadOrderService(current_user="admin").create_order(**payload)

    # El camion ajeno ni siquiera es del transportista; tampoco debe colarse.
    payload["truck"] = other_truck
    with pytest.raises(ValueError, match="camion"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_update_load_order_changes_trailer_domain_to_valid_value(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()
    Truck.create(domain="CAMION-B", carrier=data["carrier"], trailer_domain="ACOPLADO-02")

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data), trailer_domain="ACOPLADO-01")

    updated = service.update_order(order, trailer_domain="ACOPLADO-02")
    assert LoadOrder.get_by_id(order.id).trailer_domain == "ACOPLADO02"
    assert updated.trailer_domain == "ACOPLADO02"


def test_update_load_order_clears_trailer_domain_with_none(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data), trailer_domain="ACOPLADO-01")

    updated = service.update_order(order, trailer_domain=None)
    assert updated.trailer_domain is None
    assert LoadOrder.get_by_id(order.id).trailer_domain is None


def test_update_load_order_rejects_trailer_outside_new_carrier(db):
    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()

    other_carrier = Carrier.create(name="Otro")
    other_driver = Driver.create(name="Otro Chofer", carrier=other_carrier)
    other_truck = Truck.create(
        domain="OTRO-123",
        trailer_domain="ACOPLADO-OTRO",
        carrier=other_carrier,
    )

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data), trailer_domain="ACOPLADO-01")

    with pytest.raises(ValueError, match="transportista"):
        service.update_order(
            order,
            carrier=other_carrier,
            driver=other_driver,
            truck=other_truck,
        )


def test_update_load_order_rejects_explicit_invalid_trailer(db):
    from app.models.masters import Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()
    Truck.create(domain="CAMION-B", carrier=data["carrier"], trailer_domain="ACOPLADO-02")

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data), trailer_domain="ACOPLADO-01")

    with pytest.raises(ValueError, match="semi/acoplado"):
        service.update_order(order, trailer_domain="INVALIDO-99")


def test_legacy_order_without_trailer_domain_keeps_working(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADO-01"
    data["truck"].save()

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))
    assert order.trailer_domain is None

    # Editar sin pasar trailer_domain debe respetar el snapshot guardado.
    refreshed = service.update_order(order, observations="Editada sin trailer")
    assert refreshed.trailer_domain is None
    assert LoadOrder.get_by_id(order.id).trailer_domain is None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def test_load_order_entry_dialog_has_trailer_combo(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="trailer_ui"), "trailer_ui")
    app.processEvents()

    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    assert trailer_combo is not None
    label_texts = [label.text() for label in trailer_combo.parent().findChildren(QLabel)]
    assert any("Semi / Acoplado" == text for text in label_texts)


def test_trailer_combo_loads_options_from_driver_carrier(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Carrier Trailers")
    Driver.create(name="Chofer sin trailer", carrier=carrier)
    driver_with = Driver.create(name="Chofer con trailer", carrier=carrier)
    Truck.create(domain="CAM-A", carrier=carrier, trailer_domain="SEMIAAA")
    Truck.create(domain="CAM-B", carrier=carrier, trailer_domain="SEMIBBB")
    Truck.create(domain="CAM-C", carrier=carrier)  # sin trailer
    Truck.create(domain="OTROTRA", carrier=Carrier.create(name="Otro"), trailer_domain="SEMIOTRO")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_t"), "ui_t")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver_with.id)
    app.processEvents()

    options = [trailer_combo.itemData(i) for i in range(trailer_combo.count()) if trailer_combo.itemData(i)]
    assert "SEMIAAA" in options
    assert "SEMIBBB" in options
    assert "SEMIOTRO" not in options  # sólo del transportista del chofer
    assert len(options) == 2


def test_trailer_combo_does_not_show_duplicates(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Dup")
    driver = Driver.create(name="Dup driver", carrier=carrier)
    Truck.create(domain="DUP-A", carrier=carrier, trailer_domain="SEMIDUP")
    Truck.create(domain="DUP-B", carrier=carrier, trailer_domain="SEMIDUP")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="dup"), "dup")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    app.processEvents()

    values = [trailer_combo.itemData(i) for i in range(trailer_combo.count()) if trailer_combo.itemData(i)]
    assert values.count("SEMIDUP") == 1


def test_trailer_combo_autoselects_when_only_one_option(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Unico")
    driver = Driver.create(name="Chofer unico", carrier=carrier)
    Truck.create(domain="CAM-X", carrier=carrier, trailer_domain="SEMIUNICO")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="u"), "u")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    app.processEvents()

    assert trailer_combo.currentData() == "SEMIUNICO"


def test_trailer_combo_prefers_usual_truck_trailer(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Habitual")
    usual_truck = Truck.create(domain="CAM-1", carrier=carrier, trailer_domain="SEMIHABITUAL")
    other_truck = Truck.create(domain="CAM-2", carrier=carrier, trailer_domain="SEMIOTRO")
    driver = Driver.create(name="Chofer habitual", carrier=carrier, usual_truck=usual_truck)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="h"), "h")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    app.processEvents()

    assert trailer_combo.currentData() == "SEMIHABITUAL"


def test_trailer_combo_clears_invalid_selection_when_driver_changes(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier_one = Carrier.create(name="Carrier Uno")
    carrier_two = Carrier.create(name="Carrier Dos")
    driver_one = Driver.create(name="Chofer Uno", carrier=carrier_one)
    driver_two = Driver.create(name="Chofer Dos", carrier=carrier_two)
    Truck.create(domain="A1", carrier=carrier_one, trailer_domain="SEMIUNO")
    Truck.create(domain="B1", carrier=carrier_two, trailer_domain="SEMIDOS")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="c"), "c")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver_one.id)
    app.processEvents()
    assert trailer_combo.currentData() == "SEMIUNO"

    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver_two.id)
    app.processEvents()
    assert trailer_combo.currentData() == "SEMIDOS"
    assert "SEMIUNO" not in [
        trailer_combo.itemData(i) for i in range(trailer_combo.count()) if trailer_combo.itemData(i)
    ]


def test_trailer_combo_allows_empty_when_driver_has_no_trailers(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Sin trailers")
    driver = Driver.create(name="Chofer sin trailers", carrier=carrier)
    Truck.create(domain="SIN-1", carrier=carrier)  # sin trailer

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="s"), "s")
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    app.processEvents()

    values = [trailer_combo.itemData(i) for i in range(trailer_combo.count()) if trailer_combo.itemData(i)]
    assert values == []


def test_load_order_dialog_persists_trailer_from_combo(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.load_orders import LoadOrder
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Persistencia trailer")
    driver = Driver.create(name="Chofer Persist", carrier=carrier)
    truck = Truck.create(domain="PERS-01", carrier=carrier, trailer_domain="SEMIPERS")
    client = Client.create(name="Cliente Trailer", cuit="30727272001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Trailer",
    )
    product = Product.create(name="Prod Trailer", unit="kg")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="persist"), "persist")
    app.processEvents()
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    assert trailer_combo.currentData() == "SEMIPERS"

    dialog.destinations = [
        {
            "client_id": client.id,
            "address_id": address.id,
            "client_label": client.name,
            "address_label": address.address,
            "products": [
                {
                    "product_id": product.id,
                    "product_label": product.name,
                    "quantity": 10,
                    "unit": product.unit,
                    "precio_neto_unitario": 0,
                    "descuento_porcentaje": 0,
                    "iva_porcentaje": 21,
                    "total": 0,
                }
            ],
        }
    ]
    dialog._render_destinations()
    dialog._save()

    assert dialog.created_order is not None
    assert LoadOrder.get_by_id(dialog.created_order.id).trailer_domain == "SEMIPERS"


def test_load_order_dialog_edit_recovers_trailer_snapshot(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADOEDIT"
    data["truck"].save()

    service = LoadOrderService(current_user="edit")
    order = service.create_order(**_valid_order_payload(data), trailer_domain="ACOPLADOEDIT")

    dialog = LoadOrderEntryDialog(service, "edit", order=order)
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    assert trailer_combo.currentData() == "ACOPLADOEDIT"


def test_load_order_dialog_edit_legacy_order_without_trailer_opens_clean(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    service = LoadOrderService(current_user="legacy")
    legacy_order = service.create_order(**_valid_order_payload(data))
    assert legacy_order.trailer_domain is None

    dialog = LoadOrderEntryDialog(service, "legacy", order=legacy_order)
    app.processEvents()
    trailer_combo = dialog.findChild(QComboBox, "loadOrderTrailerInput")
    assert trailer_combo.currentData() in (None, "")


# ---------------------------------------------------------------------------
# Impresion
# ---------------------------------------------------------------------------


def test_print_service_renders_trailer_snapshot_in_transport_table(db, tmp_path):
    from app.models.masters import Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "SEMIPRINT"
    data["truck"].save()

    order = LoadOrderService(current_user="admin").create_order(
        **_valid_order_payload(data),
        trailer_domain="SEMIPRINT",
    )

    service = LoadOrderPrintService(current_user="admin")
    transport_table = service._transport_table(order)

    cell_values = []
    for row in transport_table._cellvalues:
        for cell in row:
            text = cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)
            cell_values.append(text)

    assert "Dominio semi/acoplado:" in cell_values
    assert "SEMIPRINT" in cell_values


def test_print_service_renders_dash_when_trailer_is_null(db, tmp_path):
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    service = LoadOrderPrintService(current_user="admin")
    transport_table = service._transport_table(order)
    cell_values = []
    for row in transport_table._cellvalues:
        for cell in row:
            text = cell.getPlainText() if hasattr(cell, "getPlainText") else str(cell)
            cell_values.append(text)

    assert "Dominio semi/acoplado:" in cell_values
    assert "-" in cell_values


def test_print_service_uses_snapshot_not_truck_domain(db, tmp_path):
    """Si la patente del camión cambia despues, la impresion sigue mostrando la
    patente que estaba guardada en la orden (snapshot)."""
    from pypdf import PdfReader

    from app.models.masters import Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["truck"].trailer_domain = "ACOPLADOORIGEN"
    data["truck"].save()

    order = LoadOrderService(current_user="admin").create_order(
        **_valid_order_payload(data),
        trailer_domain="ACOPLADOORIGEN",
    )

    # Cambio el trailer del camion: la impresion no debe leerlo de aca.
    data["truck"].trailer_domain = "ACOPLADONUEVO"
    data["truck"].save()

    service = LoadOrderPrintService(current_user="admin")
    pdf_path = service.export_pdf(order, tmp_path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "ACOPLADOORIGEN" in text
    assert "ACOPLADONUEVO" not in text
    assert "Dominio semi/acoplado:" in text


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_ensure_runtime_schema_adds_trailer_domain_to_legacy_loadorder():
    from peewee import SqliteDatabase

    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema
    from app.models import ALL_MODELS

    legacy_db = SqliteDatabase(":memory:", pragmas={"foreign_keys": 1})
    bind_database(legacy_db)
    legacy_db.connect(reuse_if_open=True)
    try:
        legacy_db.execute_sql(
            """
            CREATE TABLE loadorder (
                id INTEGER PRIMARY KEY,
                order_number INTEGER NOT NULL UNIQUE,
                date DATE NOT NULL,
                carrier_id INTEGER NOT NULL,
                driver_id INTEGER NOT NULL,
                truck_id INTEGER NOT NULL,
                status VARCHAR(255) NOT NULL,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )

        ensure_runtime_schema(legacy_db)

        columns = {column.name for column in legacy_db.get_columns("loadorder")}
        assert "trailer_domain" in columns
    finally:
        legacy_db.drop_tables(ALL_MODELS)
        legacy_db.close()


def test_build_load_order_form_spec_contains_trailer_label():
    from app.ui.load_orders import build_load_order_form_spec

    spec = build_load_order_form_spec()
    transport = next(section for section in spec.sections if section.title == "Transporte")
    assert "Semi / Acoplado" in transport.fields

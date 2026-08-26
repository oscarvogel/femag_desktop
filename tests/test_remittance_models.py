import pytest
from peewee import IntegrityError


def _create_remittance(data, *, internal="REM-00000001", point="0001", physical="00010678"):
    from app.models.remittances import Remittance

    return Remittance.create(
        remittance_number=internal,
        physical_point_of_sale=point,
        physical_number=physical,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        client_name=data["client"].name,
        client_cuit=data["client"].cuit,
        client_iva_condition=data["client"].iva_condition,
        delivery_address_text=data["address"].address,
        delivery_city=data["address"].city,
        delivery_province=data["address"].province,
        carrier_name=data["carrier"].name,
        carrier_cuit=data["carrier"].cuit,
        truck_domain=data["truck"].domain,
        trailer_domain=data["truck"].trailer_domain,
        driver_name=data["driver"].name,
        driver_document=data["driver"].document,
    )


def test_remittance_keeps_print_snapshot_when_master_data_changes(db):
    from tests.conftest import _master_data

    data = _master_data()
    data["truck"].trailer_domain = "AC456EF"
    data["truck"].save()
    remittance = _create_remittance(data)

    data["client"].name = "Cliente cambiado"
    data["client"].save()
    data["address"].address = "Otro domicilio"
    data["address"].save()
    data["truck"].trailer_domain = "OTRO999"
    data["truck"].save()

    remittance = type(remittance).get_by_id(remittance.id)
    assert remittance.client_name == "Cliente FEMAG"
    assert remittance.delivery_address_text == "Ruta 12"
    assert remittance.truck_domain == "AB123CD"
    assert remittance.trailer_domain == "AC456EF"


def test_physical_remittance_number_is_unique_inside_point_of_sale(db):
    from tests.conftest import _master_data

    data = _master_data()
    _create_remittance(data)

    with pytest.raises(IntegrityError):
        _create_remittance(data, internal="REM-00000002")

    other = _create_remittance(
        data,
        internal="REM-00000003",
        point="0002",
        physical="00010678",
    )
    assert other.id is not None


def test_remittance_item_stores_printed_description(db):
    from app.models.remittances import RemittanceItem
    from tests.conftest import _master_data

    data = _master_data()
    remittance = _create_remittance(data)
    item = RemittanceItem.create(
        remittance=remittance,
        product=data["product"],
        product_name=data["product"].name,
        printed_description="BOL FECULA 2° CALIDAD",
        quantity=760,
        unit="bolsa",
    )

    assert item.printed_description == "BOL FECULA 2° CALIDAD"
    assert float(item.quantity) == 760.0

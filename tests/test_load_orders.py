import pytest


def _master_data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
    driver = Driver.create(name="Juan Perez", document="123")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    product = Product.create(name="Fecula de mandioca", unit="kg")
    other_product = Product.create(name="Almidon", unit="bolsa")
    pallet = PalletType.create(type="Pallet comun", measure="1x1", weight=12.5)
    return {
        "client": client,
        "address": address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "product": product,
        "other_product": other_product,
        "pallet": pallet,
    }


def test_create_load_order_with_products_pallets_blocks_driver_and_audits(db):
    from app.models.audit import AuditLog
    from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[
            {"product": data["product"], "quantity": 1000, "observations": "Bolsas nuevas"},
            {"product": data["other_product"], "quantity": 25, "unit": "bolsa"},
        ],
        pallets=[
            {
                "pallet_type": data["pallet"],
                "measure": "1x1",
                "weight": 12.5,
                "quantity": 10,
                "observations": "Buenos",
            }
        ],
        observations="Carga urgente",
    )

    refreshed_driver = type(data["driver"]).get_by_id(data["driver"].id)

    assert order.order_number == 1
    assert order.status == LoadOrder.STATUS_DRAFT
    assert order.created_by == "admin"
    assert refreshed_driver.available is False
    assert LoadOrder.select().count() == 1
    assert LoadOrderProduct.select().where(LoadOrderProduct.order == order).count() == 2
    assert LoadOrderPallet.select().where(LoadOrderPallet.order == order).count() == 1
    assert AuditLog.select().where(AuditLog.module == "Ordenes de carga").count() >= 2


def test_blocked_driver_cannot_be_reused_until_order_is_closed_or_annulled(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.create_order(
            client=data["client"],
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": data["product"], "quantity": 50}],
            pallets=[],
        )

    service.change_status(first, LoadOrder.STATUS_CLOSED)
    assert type(data["driver"]).get_by_id(data["driver"].id).available is True

    second = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 50}],
        pallets=[],
    )
    service.annul_order(second, can_annul=True, reason="Cliente cancela")

    assert type(data["driver"]).get_by_id(data["driver"].id).available is True


def test_change_active_order_to_blocked_driver_is_rejected(db):
    from app.models.masters import Driver
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_driver = Driver.create(name="Pedro Gomez", available=False)
    service = LoadOrderService(current_user="admin")
    order = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.update_order(order, driver=other_driver)


def test_available_drivers_excludes_blocked_active_drivers(db):
    from app.models.masters import Driver
    from app.services.driver_availability_service import DriverAvailabilityService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    free_driver = Driver.create(name="Chofer libre")
    LoadOrderService(current_user="admin").create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    names = [driver.name for driver in DriverAvailabilityService().available_drivers()]

    assert free_driver.name in names
    assert data["driver"].name not in names


def test_reopening_closed_order_requires_driver_availability(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )
    service.change_status(first, LoadOrder.STATUS_CLOSED)
    service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 50}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.change_status(first, LoadOrder.STATUS_PENDING)


def test_create_order_validates_required_business_fields(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")

    with pytest.raises(ValueError, match="cliente"):
        service.create_order(
            client=None,
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": data["product"], "quantity": 100}],
            pallets=[],
        )

    with pytest.raises(ValueError, match="producto"):
        service.create_order(
            client=data["client"],
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": None, "quantity": 100}],
            pallets=[],
        )

    with pytest.raises(ValueError, match="mayor a cero"):
        service.create_order(
            client=data["client"],
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": data["product"], "quantity": 0}],
            pallets=[],
        )

    with pytest.raises(ValueError, match="fecha"):
        service.create_order(
            client=data["client"],
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": data["product"], "quantity": 100}],
            pallets=[],
            order_date=None,
            require_order_date=True,
        )


def test_emit_order_requires_complete_order_and_records_status(db):
    from app.models.load_orders import LoadOrder, LoadOrderStatusHistory
    from app.models.masters import Driver
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    available_driver = Driver.create(name="Chofer disponible")
    service = LoadOrderService(current_user="admin")
    incomplete = LoadOrder.create(
        order_number=77,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_DRAFT,
    )

    with pytest.raises(ValueError, match="producto"):
        service.change_status(incomplete, LoadOrder.STATUS_ISSUED)

    complete = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=available_driver,
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    issued = service.change_status(complete, LoadOrder.STATUS_ISSUED, reason="Lista para despacho")

    assert issued.status == LoadOrder.STATUS_ISSUED
    assert (
        LoadOrderStatusHistory.select()
        .where(
            (LoadOrderStatusHistory.order == complete)
            & (LoadOrderStatusHistory.new_status == LoadOrder.STATUS_ISSUED)
        )
        .count()
        == 1
    )


def test_update_order_replaces_basic_fields_products_and_pallets(db):
    from app.models.load_orders import LoadOrderPallet, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    updated = service.update_order(
        order,
        products=[{"product": data["other_product"], "quantity": 25, "unit": "bolsa"}],
        pallets=[{"pallet_type": data["pallet"], "quantity": 4}],
        observations="Editada desde pantalla",
    )

    product_line = LoadOrderProduct.get(LoadOrderProduct.order == updated)
    pallet_line = LoadOrderPallet.get(LoadOrderPallet.order == updated)

    assert updated.observations == "Editada desde pantalla"
    assert product_line.product.id == data["other_product"].id
    assert product_line.quantity == 25
    assert pallet_line.quantity == 4


def test_list_orders_returns_rows_for_consultation(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
        observations="Consulta rápida",
    )

    rows = service.list_orders()

    assert rows[0]["id"] == order.id
    assert rows[0]["numero"] == order.order_number
    assert rows[0]["cliente"] == "Cliente FEMAG"
    assert rows[0]["producto"] == "Fecula de mandioca"
    assert rows[0]["cantidad"] == 100
    assert rows[0]["estado"] == "Borrador"

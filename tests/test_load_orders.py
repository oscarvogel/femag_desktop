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
    from app.models.load_orders import LoadOrder, LoadOrderLine
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(
        header_client_text="VARIOS",
        destination="Corrientes - Entre Rios - Buenos Aires",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        vehicle_clean_and_suitable=True,
        lines=[
            {
                "client": data["client"],
                "recipient_text": "Graef Hermanos",
                "destination_text": "Corrientes",
                "product": data["product"],
                "product_detail": "Fecula de mandioca",
                "bags_25kg": 40,
                "bags_10kg": 12,
                "pack": 3,
                "pallet": 2,
                "lot_number": "L-001",
                "production_date": "2026-06-01",
                "observations": "Bolsas nuevas",
            },
            {
                "recipient_text": "Cliente Ruta 14",
                "destination_text": "Entre Rios",
                "product": data["other_product"],
                "product_detail": "Almidon x pack",
                "bags_25kg": 5,
                "bags_10kg": 8,
                "pack": 10,
                "pallet": 1,
                "lot_number": "L-002",
                "production_date": "2026-06-02",
            },
        ],
        observations="Carga urgente",
    )

    refreshed_driver = type(data["driver"]).get_by_id(data["driver"].id)

    assert order.order_number == 1
    assert order.status == LoadOrder.STATUS_PENDING
    assert order.header_client is None
    assert order.header_client_text == "VARIOS"
    assert order.destination == "Corrientes - Entre Rios - Buenos Aires"
    assert order.vehicle_clean_and_suitable is True
    assert order.created_by == "admin"
    assert refreshed_driver.available is False
    assert LoadOrder.select().count() == 1
    assert LoadOrderLine.select().where(LoadOrderLine.order == order).count() == 2
    totals = LoadOrderService(current_user="admin").presentation_totals(order)
    assert totals == {"bags_25kg": 45, "bags_10kg": 20, "pack": 13, "pallet": 3}
    assert AuditLog.select().where(AuditLog.module == "Ordenes de carga").count() >= 2


def test_blocked_driver_cannot_be_reused_until_order_is_closed_or_annulled(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente A", "bags_25kg": 1}],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.create_order(
            header_client_text="VARIOS",
            destination="Corrientes",
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            lines=[{"recipient_text": "Cliente B", "bags_25kg": 1}],
        )

    service.change_status(first, LoadOrder.STATUS_CLOSED)
    assert type(data["driver"]).get_by_id(data["driver"].id).available is True

    second = service.create_order(
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente B", "bags_25kg": 1}],
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
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente A", "bags_25kg": 1}],
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
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente A", "bags_25kg": 1}],
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
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente A", "bags_25kg": 1}],
    )
    service.change_status(first, LoadOrder.STATUS_CLOSED)
    service.create_order(
        header_client_text="VARIOS",
        destination="Corrientes",
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        lines=[{"recipient_text": "Cliente B", "bags_25kg": 1}],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.change_status(first, LoadOrder.STATUS_PENDING)

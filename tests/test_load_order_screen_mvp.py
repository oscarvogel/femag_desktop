from datetime import date


def _screen_master_data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    other_client = Client.create(name="Otro cliente", cuit="30999999999", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 14",
    )
    carrier = Carrier.create(name="Transporte Norte")
    other_carrier = Carrier.create(name="Transporte Sur")
    driver = Driver.create(name="Juan Perez", carrier=carrier)
    other_driver = Driver.create(name="Pedro Gomez", carrier=other_carrier)
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    other_truck = Truck.create(domain="ZZ999ZZ", carrier=other_carrier)
    product = Product.create(name="Fecula de mandioca", unit="kg")
    return {
        "client": client,
        "address": address,
        "other_client": other_client,
        "other_address": other_address,
        "carrier": carrier,
        "other_carrier": other_carrier,
        "driver": driver,
        "other_driver": other_driver,
        "truck": truck,
        "other_truck": other_truck,
        "product": product,
    }


def test_load_order_screen_options_filter_dependent_fields(db):
    from app.ui.load_orders import build_load_order_screen_state

    data = _screen_master_data()

    state = build_load_order_screen_state(
        current_user="admin",
        selected_client_id=data["client"].id,
        selected_carrier_id=data["carrier"].id,
        selected_truck_id=data["truck"].id,
    )

    assert [option.label for option in state.delivery_addresses] == ["Ruta 12, Posadas"]
    assert [option.label for option in state.trucks] == ["AB123CD"]
    assert [option.label for option in state.drivers] == ["Juan Perez"]
    assert state.primary_actions == ("Nueva orden", "Guardar orden", "Anular")
    assert "Imprimir" not in state.primary_actions


def test_load_order_screen_creates_order_through_service_and_lists_it(db):
    from app.models.load_orders import LoadOrder
    from app.ui.load_orders import build_load_order_screen_state, create_load_order_from_screen

    data = _screen_master_data()

    order = create_load_order_from_screen(
        current_user="admin",
        client_id=data["client"].id,
        delivery_address_id=data["address"].id,
        carrier_id=data["carrier"].id,
        truck_id=data["truck"].id,
        driver_id=data["driver"].id,
        product_id=data["product"].id,
        quantity=125,
        observations="Carga de prueba",
        order_date=date(2026, 6, 24),
    )

    state = build_load_order_screen_state(current_user="admin")

    assert order.status == LoadOrder.STATUS_PENDING
    assert len(state.rows) == 1
    assert state.rows[0].number == "OC-000001"
    assert state.rows[0].client == "Cliente FEMAG"
    assert state.rows[0].delivery == "Ruta 12, Posadas"
    assert state.rows[0].product == "Fecula de mandioca"
    assert state.rows[0].quantity == "125 kg"
    assert state.rows[0].driver == "Juan Perez"
    assert state.rows[0].carrier == "Transporte Norte"
    assert state.rows[0].status == "Pendiente"


def test_load_order_screen_surfaces_service_validation_messages(db):
    from app.ui.load_orders import create_load_order_from_screen

    data = _screen_master_data()

    try:
        create_load_order_from_screen(
            current_user="admin",
            client_id=data["client"].id,
            delivery_address_id=data["other_address"].id,
            carrier_id=data["carrier"].id,
            truck_id=data["truck"].id,
            driver_id=data["driver"].id,
            product_id=data["product"].id,
            quantity=100,
        )
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - keeps the assertion message focused.
        raise AssertionError("Expected invalid delivery address to be rejected")

    assert "lugar de entrega debe pertenecer al cliente" in message

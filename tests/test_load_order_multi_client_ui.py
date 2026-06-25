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
    other_client = Client.create(name="Cliente Sur", cuit="30999999999", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 14",
    )
    carrier = Carrier.create(name="Transporte Norte")
    driver = Driver.create(name="Juan Perez", carrier=carrier)
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    product = Product.create(name="Fecula de mandioca", unit="kg")
    other_product = Product.create(name="Almidon", unit="bolsa")
    return {
        "client": client,
        "address": address,
        "other_client": other_client,
        "other_address": other_address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "product": product,
        "other_product": other_product,
    }


def test_load_order_form_spec_is_centered_on_logistic_header_and_client_blocks(db):
    from app.ui.load_orders import build_load_order_form_spec, build_load_order_workspace_spec

    form_spec = build_load_order_form_spec()
    workspace_spec = build_load_order_workspace_spec()

    header_fields = form_spec.sections[0].fields

    assert "Cliente" not in header_fields
    assert "Domicilio entrega" not in header_fields
    assert "Producto" not in header_fields
    assert form_spec.detail_actions == ("Agregar cliente", "Quitar cliente", "Agregar producto", "Quitar producto")
    assert form_spec.primary_actions == ("Guardar orden", "Emitir/Cerrar", "Anular")
    assert workspace_spec.table_columns[:5] == ("N° orden", "Fecha", "Clientes", "Destinos", "Productos")


def test_load_order_screen_creates_multi_client_order_through_service_and_lists_it(db):
    from app.models.load_orders import LoadOrder
    from app.ui.load_orders import build_load_order_screen_state, create_load_order_from_screen

    data = _screen_master_data()

    order = create_load_order_from_screen(
        current_user="admin",
        carrier_id=data["carrier"].id,
        truck_id=data["truck"].id,
        driver_id=data["driver"].id,
        destinations=[
            {
                "client_id": data["client"].id,
                "delivery_address_id": data["address"].id,
                "products": [{"product_id": data["product"].id, "quantity": 125}],
            },
            {
                "client_id": data["other_client"].id,
                "delivery_address_id": data["other_address"].id,
                "products": [{"product_id": data["other_product"].id, "quantity": 30}],
            },
        ],
        observations="Carga de prueba",
        order_date=date(2026, 6, 24),
    )

    state = build_load_order_screen_state(current_user="admin")

    assert order.status == LoadOrder.STATUS_PENDING
    assert len(state.rows) == 1
    assert state.rows[0].number == "OC-000001"
    assert state.rows[0].client == "VARIOS (2)"
    assert state.rows[0].delivery == "Posadas; Obera"
    assert state.rows[0].product == "2 productos"
    assert state.rows[0].quantity == "155 total"
    assert state.rows[0].driver == "Juan Perez"
    assert state.rows[0].carrier == "Transporte Norte"
    assert state.rows[0].status == "Pendiente"


def test_load_order_screen_surfaces_destination_validation_messages(db):
    from app.ui.load_orders import create_load_order_from_screen

    data = _screen_master_data()

    try:
        create_load_order_from_screen(
            current_user="admin",
            carrier_id=data["carrier"].id,
            truck_id=data["truck"].id,
            driver_id=data["driver"].id,
            destinations=[
                {
                    "client_id": data["client"].id,
                    "delivery_address_id": data["other_address"].id,
                    "products": [{"product_id": data["product"].id, "quantity": 100}],
                }
            ],
        )
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - keeps the assertion message focused.
        raise AssertionError("Expected invalid delivery address to be rejected")

    assert "lugar de entrega debe pertenecer al cliente" in message

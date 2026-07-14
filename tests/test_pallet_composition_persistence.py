from decimal import Decimal

import pytest


def _data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck

    client_a = Client.create(name="Cliente A pallets", cuit="30700000101", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito A",
    )
    client_b = Client.create(name="Cliente B pallets", cuit="30700000102", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Deposito B",
    )
    carrier = Carrier.create(name="Transporte pallets")
    driver = Driver.create(name="Chofer pallets", carrier=carrier)
    truck = Truck.create(domain="PAL123", carrier=carrier)
    product_a = Product.create(
        name="Articulo A pallets",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    product_b = Product.create(
        name="Articulo B pallets",
        unit="unidad",
        peso_unitario_kg=Decimal("10.000"),
    )
    pallet_type = PalletType.create(type="Pallet operativo", measure="1x1", weight=0)
    return locals()


def _destinations(data):
    return [
        {
            "client": data["client_a"],
            "delivery_address": data["address_a"],
            "products": [{"product": data["product_a"], "quantity": 40}],
        },
        {
            "client": data["client_b"],
            "delivery_address": data["address_b"],
            "products": [{"product": data["product_b"], "quantity": 5}],
        },
    ]


def _allocation(data, client_key, address_key, product_key, quantity):
    return {
        "client": data[client_key],
        "delivery_address": data[address_key],
        "product": data[product_key],
        "quantity": Decimal(str(quantity)),
    }


def test_create_order_persists_mixed_pallets_and_weight_snapshots(db):
    from app.models.load_orders import LoadOrderPallet, LoadOrderPalletAllocation
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="pallets")
    order = service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_destinations(data),
        pallets=[
            {
                "sequence": 1,
                "pallet_type": data["pallet_type"],
                "allocations": [
                    _allocation(data, "client_a", "address_a", "product_a", 25),
                ],
            },
            {
                "sequence": 2,
                "pallet_type": data["pallet_type"],
                "allocations": [
                    _allocation(data, "client_a", "address_a", "product_a", 15),
                    _allocation(data, "client_b", "address_b", "product_b", 5),
                ],
            },
        ],
    )

    pallets = list(LoadOrderPallet.select().where(LoadOrderPallet.order == order).order_by(LoadOrderPallet.sequence))
    assert [pallet.sequence for pallet in pallets] == [1, 2]
    assert LoadOrderPalletAllocation.select().count() == 3
    assert service.composition(order).total_kg == Decimal("1050.000")

    data["product_a"].peso_unitario_kg = Decimal("30.000")
    data["product_a"].save()
    assert service.composition(order).total_kg == Decimal("1050.000")

    service.update_order(order, destinations=_destinations(data))
    assert service.composition(order).total_kg == Decimal("1050.000")


def test_create_order_allows_pending_but_rejects_excess_assignments(db):
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="pallets")
    incomplete = service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_destinations(data),
        pallets=[
            {
                "sequence": 1,
                "pallet_type": data["pallet_type"],
                "allocations": [_allocation(data, "client_a", "address_a", "product_a", 10)],
            }
        ],
    )
    assert service.composition(incomplete).is_complete is False

    with pytest.raises(ValueError, match="excede lo solicitado"):
        service.create_order(
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            destinations=_destinations(data),
            pallets=[
                {
                    "sequence": 1,
                    "pallet_type": data["pallet_type"],
                    "allocations": [_allocation(data, "client_a", "address_a", "product_a", 41)],
                }
            ],
        )


def test_create_order_ignores_payload_weight_and_snapshots_product_master(db):
    from app.models.load_orders import LoadOrderPalletAllocation
    from app.services.load_order_service import LoadOrderService

    data = _data()
    data["product_a"].peso_unitario_kg = Decimal("0.000")
    data["product_a"].save()
    allocation = _allocation(data, "client_a", "address_a", "product_a", 40)
    allocation["peso_unitario_kg"] = Decimal("999.000")

    order = LoadOrderService(current_user="pallets").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_destinations(data),
        pallets=[{"sequence": 1, "allocations": [allocation]}],
    )

    saved = LoadOrderPalletAllocation.get()
    assert saved.peso_unitario_kg == Decimal("0.000")


def test_updating_requested_merchandise_preserves_valid_pallet_assignments(db):
    from app.models.load_orders import LoadOrderPalletAllocation
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="pallets")
    order = service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_destinations(data),
        pallets=[
            {
                "sequence": 1,
                "pallet_type": data["pallet_type"],
                "allocations": [_allocation(data, "client_a", "address_a", "product_a", 40)],
            },
            {
                "sequence": 2,
                "pallet_type": data["pallet_type"],
                "allocations": [_allocation(data, "client_b", "address_b", "product_b", 5)],
            },
        ],
    )

    service.update_order(order, destinations=list(reversed(_destinations(data))))

    assert LoadOrderPalletAllocation.select().count() == 2
    assignments = {
        allocation.product.name: allocation.destination.client.name
        for allocation in LoadOrderPalletAllocation.select()
    }
    assert assignments == {
        "Articulo A pallets": "Cliente A pallets",
        "Articulo B pallets": "Cliente B pallets",
    }
    assert service.composition(order).total_kg == Decimal("1050.000")

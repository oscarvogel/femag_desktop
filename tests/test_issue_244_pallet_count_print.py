from decimal import Decimal


def _build_order_with_mixed_pallet(db):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente issue 244", cuit="30700024401", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito issue 244",
    )
    carrier = Carrier.create(name="Transporte issue 244")
    driver = Driver.create(name="Chofer issue 244", carrier=carrier)
    truck = Truck.create(domain="ISS244", carrier=carrier)
    product_a = Product.create(name="Nativa issue 244", unit="bolsas", peso_unitario_kg=Decimal("25.000"))
    product_b = Product.create(name="Maiz issue 244", unit="bolsas", peso_unitario_kg=Decimal("25.000"))

    return LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {"product": product_a, "quantity": 100},
                    {"product": product_b, "quantity": 50},
                ],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "allocations": [
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": product_a,
                        "quantity": 50,
                    }
                ],
            },
            {
                "sequence": 3,
                "allocations": [
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": product_a,
                        "quantity": 50,
                    },
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": product_b,
                        "quantity": 50,
                    },
                ],
            },
        ],
    )


def test_issue_244_detail_blocks_group_by_pallet_instead_of_sequences(db):
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _build_order_with_mixed_pallet(db)
    service = LoadOrderPrintService(current_user="admin")

    blocks = service._detail_blocks(order)

    assert len(blocks) == 1
    block = blocks[0]
    assert [pallet["label"] for pallet in block["pallet_blocks"]] == ["1", "3"]
    assert [len(pallet["rows"]) for pallet in block["pallet_blocks"]] == [1, 2]
    assert service._used_pallet_total(order) == 2


def test_issue_244_mixed_pallet_is_counted_once_as_a_single_printed_block(db):
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _build_order_with_mixed_pallet(db)
    service = LoadOrderPrintService(current_user="admin")
    blocks = service._detail_blocks(order)

    mixed = blocks[0]["pallet_blocks"][1]
    assert mixed["label"] == "3"
    assert len(mixed["rows"]) == 2
    assert [row["product"] for row in mixed["rows"]] == ["Nativa issue 244", "Maiz issue 244"]
    assert service._used_pallet_total(order) == 2

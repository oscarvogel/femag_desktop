import re
from decimal import Decimal

from pypdf import PdfReader


def test_issue_417_order_0078_pdf_totals_all_physical_pallets(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte issue 417")
    driver = Driver.create(name="Chofer issue 417", carrier=carrier)
    truck = Truck.create(domain="ISS417", carrier=carrier)
    product = Product.create(
        name="BOLSAS DE FECULA NATIVA",
        unit="UNIDAD",
        peso_unitario_kg=Decimal("25.000"),
    )
    distributions = [
        ("Molinos Río de la Plata", 13),
        ("Distribuidora de Mat. Primas", 2),
        ("Huerta Mama Cora", 3),
        ("García Abel Carlos", 1),
    ]
    destinations = []
    pallet_payloads = []
    sequence = 1

    for destination_index, (client_name, pallet_count) in enumerate(distributions):
        client = Client.create(
            name=client_name,
            cuit=f"307000417{destination_index:02d}",
            iva_condition="RI",
        )
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city="Posadas",
            address=f"Destino issue 417 {destination_index}",
        )
        destinations.append(
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": pallet_count * 60}],
            }
        )
        for _ in range(pallet_count):
            pallet_payloads.append(
                {
                    "sequence": sequence,
                    "allocations": [
                        {
                            "client": client,
                            "delivery_address": address,
                            "product": product,
                            "quantity": 60,
                        }
                    ],
                }
            )
            sequence += 1

    order = LoadOrderService(current_user="issue-417-test").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=destinations,
        pallets=pallet_payloads,
    )
    pdf_path = ConsolidatedLoadOrderPrintService(current_user="issue-417-test").export_pdf(
        order,
        tmp_path,
    )
    pages = PdfReader(str(pdf_path)).pages
    pdf_text = "\n".join(page.extract_text() or "" for page in pages)

    assert pdf_path.read_bytes().startswith(b"%PDF")
    printed_quantities = [
        int(quantity)
        for quantity in re.findall(r"(?m)^\s*(\d+)\s+UNIDADES$", pdf_text)
    ]
    assert printed_quantities == [780, 120, 180, 60]
    assert sum(printed_quantities) == 1140
    assert re.search(r"(?m)^\s*1140\s*$", pdf_text)
    assert "BOLSAS DE FECULA NATIVA" in pdf_text
    assert "19 pallets" in pdf_text
    assert "28.500 kg" in pdf_text
    assert "TOTALES" in pdf_text
    assert "19 pallets" in (pages[0].extract_text() or "")
    if len(pages) > 1:
        assert "Firma del encargado de carga" in (pages[-1].extract_text() or "")


def test_shared_products_on_one_mixed_pallet_count_once_in_pdf(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService

    client = Client.create(name="Cliente pallet mixto issue 417", cuit="30700041710", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino mixto issue 417",
    )
    product_a = Product.create(name="Producto A issue 417", unit="UNIDAD", peso_unitario_kg=25)
    product_b = Product.create(name="Producto B issue 417", unit="UNIDAD", peso_unitario_kg=25)
    carrier = Carrier.create(name="Transporte mixto issue 417")
    driver = Driver.create(name="Chofer mixto issue 417", carrier=carrier)
    truck = Truck.create(domain="ISS417MIX", carrier=carrier)
    order = LoadOrderService(current_user="issue-417-test").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {"product": product_a, "quantity": 30},
                    {"product": product_b, "quantity": 45},
                ],
            }
        ],
        pallets=[
            {
                "sequence": 19,
                "allocations": [
                    {"client": client, "delivery_address": address, "product": product_a, "quantity": 30},
                    {"client": client, "delivery_address": address, "product": product_b, "quantity": 45},
                ],
            }
        ],
    )
    pdf_path = ConsolidatedLoadOrderPrintService(current_user="issue-417-test").export_pdf(order, tmp_path)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "1 pallet" in pdf_text
    assert "2 pallets" not in pdf_text
    assert "1 pallets" not in pdf_text
    assert "1.875 kg" in pdf_text


def test_single_client_with_multiple_pallets_uses_physical_count_in_pdf(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService

    client = Client.create(name="Cliente unico issue 417", cuit="30700041711", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino unico issue 417",
    )
    product = Product.create(name="Producto unico issue 417", unit="UNIDAD", peso_unitario_kg=25)
    carrier = Carrier.create(name="Transporte unico issue 417")
    driver = Driver.create(name="Chofer unico issue 417", carrier=carrier)
    truck = Truck.create(domain="ISS417ONE", carrier=carrier)
    order = LoadOrderService(current_user="issue-417-test").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 180}],
            }
        ],
        pallets=[
            {
                "sequence": sequence,
                "allocations": [
                    {"client": client, "delivery_address": address, "product": product, "quantity": 60}
                ],
            }
            for sequence in (7, 8, 9)
        ],
    )
    pdf_path = ConsolidatedLoadOrderPrintService(current_user="issue-417-test").export_pdf(order, tmp_path)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "180 UNIDADES" in pdf_text
    assert "3 pallets" in pdf_text
    assert "9 pallets" not in pdf_text


def test_total_counts_all_physical_pallets_even_without_allocations(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService

    carrier = Carrier.create(name="Transporte total destinos issue 417")
    driver = Driver.create(name="Chofer total destinos issue 417", carrier=carrier)
    truck = Truck.create(domain="ISS417DST", carrier=carrier)
    product = Product.create(name="Producto destinos issue 417", unit="UNIDAD", peso_unitario_kg=25)
    distributions = [
        ("Cliente 13", 13, set(range(1, 14))),
        ("Cliente 2", 2, {1, 2}),
        ("Cliente 3", 3, {1, 2, 3}),
        ("Cliente 1", 1, {1}),
    ]
    destinations = []
    destination_allocations = []
    for index, (name, pallet_count, pallet_sequences) in enumerate(distributions):
        client = Client.create(name=name, cuit=f"307000418{index:02d}", iva_condition="RI")
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city="Posadas",
            address=f"Destino {name}",
        )
        destinations.append(
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": pallet_count * 60}],
            }
        )
        destination_allocations.append(
            {
                "client": client,
                "delivery_address": address,
                "pallet_sequences": pallet_sequences,
            }
        )

    # The real order has 19 physical pallet records. Destination allocations
    # refer to 13 of them, with the first three shared across destinations;
    # six pallet records have no product allocation.
    pallets = []
    for sequence in range(1, 20):
        allocations = [
            {
                "client": destination["client"],
                "delivery_address": destination["delivery_address"],
                "product": product,
                "quantity": 60,
            }
            for destination in destination_allocations
            if sequence in destination["pallet_sequences"]
        ]
        pallets.append({"sequence": sequence, "allocations": allocations})

    order = LoadOrderService(current_user="issue-417-test").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=destinations,
        pallets=pallets,
    )

    pdf_path = ConsolidatedLoadOrderPrintService(current_user="issue-417-test").export_pdf(order, tmp_path)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "19 pallets" in pdf_text
    assert "13 pallets" in pdf_text

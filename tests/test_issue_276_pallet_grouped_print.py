from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from load_order_printing_cases import _pdf_text


def _data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck

    client = Client.create(name="MASTER CEREAL", cuit="30700276001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="VIENTO NORTE",
    )
    carrier = Carrier.create(name="Transporte 276")
    driver = Driver.create(name="Chofer 276", carrier=carrier)
    truck = Truck.create(domain="GRP276", carrier=carrier)
    return {
        "client": client,
        "address": address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
    }


def _create(data, destinations, pallets, loose=None):
    from app.services.load_order_service import LoadOrderService

    return LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=destinations,
        pallets=pallets or [],
        loose_allocations=loose or [],
    )


def _destination(data, products):
    return [
        {
            "client": data["client"],
            "delivery_address": data["address"],
            "products": [{"product": product, "quantity": quantity} for product, quantity in products],
        }
    ]


def _allocations(data, product, quantity):
    return [
        {
            "client": data["client"],
            "delivery_address": data["address"],
            "product": product,
            "quantity": Decimal(str(quantity)),
        }
    ]


def test_case_1_simple_pallet_prints_once_with_product_and_count(db, tmp_path):
    from app.models.masters import Product
    from app.services.load_order_print_service import LoadOrderPrintService

    data = _data()
    product = Product.create(name="NATIVA 500g", unit="pack")
    order = _create(data, _destination(data, [(product, 50)]), [{"sequence": 19, "allocations": _allocations(data, product, 50)}])
    service = LoadOrderPrintService(current_user="admin")

    blocks = service._detail_blocks(order)
    assert len(blocks) == 1
    pallets = blocks[0]["pallet_blocks"]
    assert len(pallets) == 1
    assert pallets[0]["label"] == "19"
    assert len(pallets[0]["rows"]) == 1
    assert pallets[0]["rows"][0]["quantity"] == 50.0
    assert pallets[0]["rows"][0]["product"] == "NATIVA 500g"
    assert service._used_pallet_total(order) == 1

    text = _pdf_text(service.export_pdf(order, tmp_path))
    assert "19" in text
    assert "NATIVA 500g" in text
    assert "1 pallet" in text


def test_case_2_mixed_pallet_three_allocations_in_one_grouped_block(db, tmp_path):
    from app.models.load_orders import LoadOrderProduct
    from app.models.masters import Product
    from app.services.load_order_print_service import LoadOrderPrintService

    data = _data()
    almidon = Product.create(name="ALMIDÓN DE MAÍZ", unit="pack")
    nativa_500 = Product.create(name="NATIVA 500g", unit="pack")
    nativa_1kg = Product.create(name="NATIVA 1kg", unit="pack")
    order = _create(
        data,
        _destination(data, [(almidon, 10), (nativa_500, 50), (nativa_1kg, 50)]),
        [
            {
                "sequence": 19,
                "allocations": _allocations(data, almidon, 10)
                + _allocations(data, nativa_500, 50)
                + _allocations(data, nativa_1kg, 50),
            }
        ],
    )
    row = LoadOrderProduct.get(order=order, product=almidon)
    row.lote = "LOTE-19"
    row.fecha_elaboracion = date(2026, 3, 5)
    row.save()
    service = LoadOrderPrintService(current_user="admin")

    blocks = service._detail_blocks(order)
    assert len(blocks) == 1
    pallets = blocks[0]["pallet_blocks"]
    assert len(pallets) == 1
    mixed = pallets[0]
    assert mixed["label"] == "19"
    assert len(mixed["rows"]) == 3
    assert [r["product"] for r in mixed["rows"]] == ["ALMIDÓN DE MAÍZ", "NATIVA 500g", "NATIVA 1kg"]
    assert [r["quantity"] for r in mixed["rows"]] == [10.0, 50.0, 50.0]
    assert service._used_pallet_total(order) == 1

    almidon_row = next(r for r in mixed["rows"] if r["product"] == "ALMIDÓN DE MAÍZ")
    assert almidon_row["lote"] == "LOTE-19"
    assert almidon_row["elab"] == "05/03/26"

    table = service._destination_table(blocks[0])
    assert ("SPAN", (2, 2), (2, 4)) in table._spanCmds
    assert table._cellvalues[2][2].getPlainText() == "19"

    text = _pdf_text(service.export_pdf(order, tmp_path))
    normalized_text = " ".join(text.split())
    assert "19" in normalized_text
    assert "ALMIDÓN DE MAÍZ" in normalized_text
    assert "NATIVA 500g" in normalized_text
    assert "NATIVA 1kg" in normalized_text
    # Desde #301, lote y elaboración quedan vacíos en la impresión operativa para carga manual.
    assert "LOTE-19" not in normalized_text
    assert "05/03/26" not in normalized_text
    assert "3 pallets" not in normalized_text
    assert "1 pallet" in normalized_text


def test_case_3_two_pallets_same_client_are_independent_blocks(db, tmp_path):
    from app.models.masters import Product
    from app.services.load_order_print_service import LoadOrderPrintService

    data = _data()
    product_a = Product.create(name="Producto A 276", unit="bolsas")
    product_b = Product.create(name="Producto B 276", unit="bolsas")
    product_c = Product.create(name="Producto C 276", unit="bolsas")
    order = _create(
        data,
        _destination(data, [(product_a, 50), (product_b, 50), (product_c, 50)]),
        [
            {"sequence": 1, "allocations": _allocations(data, product_a, 50)},
            {"sequence": 2, "allocations": _allocations(data, product_b, 30) + _allocations(data, product_c, 50)},
        ],
    )
    service = LoadOrderPrintService(current_user="admin")

    blocks = service._detail_blocks(order)
    pallets = blocks[0]["pallet_blocks"]
    assert [p["label"] for p in pallets] == ["1", "2"]
    assert len(pallets[0]["rows"]) == 1
    assert [r["product"] for r in pallets[1]["rows"]] == ["Producto B 276", "Producto C 276"]
    assert service._used_pallet_total(order) == 2

    table = service._destination_table(blocks[0])
    assert ("SPAN", (2, 3), (2, 4)) in table._spanCmds

    unassigned = blocks[0]["unassigned_block"]
    assert unassigned is not None
    assert unassigned["label"] == "-"
    assert unassigned["rows"][0]["product"] == "Producto B 276"
    assert unassigned["rows"][0]["quantity"] == 20.0


def test_case_4_pallet_grouping_never_mixes_destinations(db, tmp_path):
    from app.models.masters import Client, ClientAddress, Product
    from app.services.load_order_print_service import LoadOrderPrintService

    data = _data()
    other_client = Client.create(name="DESTINO DOS 276", cuit="30700276002", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito dos 276",
    )
    product_a = Product.create(name="Almidon A 276", unit="bolsas")
    product_b = Product.create(name="Almidon B 276", unit="bolsas")
    order = _create(
        data,
        [
            {"client": data["client"], "delivery_address": data["address"], "products": [{"product": product_a, "quantity": 40}]},
            {"client": other_client, "delivery_address": other_address, "products": [{"product": product_b, "quantity": 60}]},
        ],
        [
            {
                "sequence": 7,
                "allocations": _allocations(data, product_a, 40)
                + [
                    {
                        "client": other_client,
                        "delivery_address": other_address,
                        "product": product_b,
                        "quantity": Decimal("60"),
                    }
                ],
            }
        ],
    )
    service = LoadOrderPrintService(current_user="admin")

    blocks = service._detail_blocks(order)
    assert len(blocks) == 2
    assert [p["label"] for p in blocks[0]["pallet_blocks"]] == ["7"]
    assert [r["product"] for r in blocks[0]["pallet_blocks"][0]["rows"]] == ["Almidon A 276"]
    assert [r["product"] for r in blocks[1]["pallet_blocks"][0]["rows"]] == ["Almidon B 276"]
    assert service._used_pallet_total(order) == 1

    text = _pdf_text(service.export_pdf(order, tmp_path))
    normalized_text = " ".join(text.split())
    assert "Almidon A 276" in normalized_text
    assert "Almidon B 276" in normalized_text
    assert "1 pallet" in normalized_text


def test_case_5_multipage_keeps_headers_and_generates_without_layout_error(db, tmp_path):
    from app.models.masters import Product
    from app.services.load_order_print_service import LoadOrderPrintService

    data = _data()
    product = Product.create(name="Multipage 276", unit="bolsas")
    pallets = []
    for sequence in range(1, 81):
        pallets.append({"sequence": sequence, "allocations": _allocations(data, product, 10)})
    order = _create(data, _destination(data, [(product, 800)]), pallets)
    service = LoadOrderPrintService(current_user="admin")

    pdf_path = service.export_pdf(order, tmp_path)
    reader = PdfReader(str(pdf_path))
    assert len(reader.pages) >= 2
    text = _pdf_text(pdf_path)
    normalized_text = " ".join(text.split())
    assert "Cliente / destino" in normalized_text
    assert "80 pallets" in normalized_text
    second_page = " ".join((reader.pages[1].extract_text() or "").split())
    assert "Cliente / destino" in second_page

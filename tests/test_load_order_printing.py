from pathlib import Path

from pypdf import PdfReader


def _order():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
    )
    carrier = Carrier.create(name="Transporte Norte")
    driver = Driver.create(name="Juan Perez", carrier=carrier)
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    product = Product.create(name="Fecula", unit="kg")
    pallet = PalletType.create(type="Comun", measure="1x1", weight=12.5)
    return LoadOrderService(current_user="admin").create_order(
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        products=[{"product": product, "quantity": 1000}],
        pallets=[{"pallet_type": pallet, "measure": "1x1", "weight": 12.5, "quantity": 8}],
        observations="Imprimir con hoja resumen",
    )


def _pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_print_service_exports_load_order_pdf_with_real_format_fields(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _order()
    service = LoadOrderPrintService(current_user="admin")

    pdf_path = service.export_pdf(order, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.name == "orden_carga_1.pdf"
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "GRAEF HERMANOS S.R.L." in text
    assert "ORDEN DE DESPACHO DE FECULA DE MANDIOCA" in text
    assert "Nro.: 0001" in text
    assert "1. DATOS DEL CLIENTE" in text
    assert "Cliente FEMAG" in text
    assert "Ruta 12" in text
    assert "2. DETALLE DEL PRODUCTO A DESPACHAR" in text
    assert "Fecula" in text
    assert "1000" in text
    assert "3. DATOS DEL TRANSPORTE" in text
    assert "Transporte Norte" in text
    assert "Juan Perez" in text
    assert "AB123CD" in text
    assert "Imprimir con hoja resumen" in text
    assert "Firma del encargado de carga" in text
    assert AuditLog.select().where(AuditLog.action == "imprimir").count() == 1


def test_print_service_groups_multi_client_order_by_destination(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
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
    product = Product.create(name="Fecula", unit="kg")
    other_product = Product.create(name="Almidon", unit="bolsa")
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 1000}],
            },
            {
                "client": other_client,
                "delivery_address": other_address,
                "products": [{"product": other_product, "quantity": 25}],
            },
        ],
        pallets=[],
    )

    pdf_path = LoadOrderPrintService(current_user="admin").export_pdf(order, tmp_path)
    text = _pdf_text(pdf_path)

    assert "VARIOS" in text
    assert "Ruta 12" in text
    assert "Ruta 14" in text
    assert "Cliente FEMAG" in text
    assert "Fecula" in text
    assert "Cliente Sur" in text
    assert "Almidon" in text


def test_final_a4_print_separates_logistics_destinations_and_totals(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente Norte", cuit="30710000001", iva_condition="RI")
    north_address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Parque Industrial",
    )
    south_client = Client.create(name="Cliente Sur", cuit="30710000002", iva_condition="RI")
    south_address = ClientAddress.create(
        client=south_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Deposito Sur",
    )
    carrier = Carrier.create(name="Transporte Ruta")
    driver = Driver.create(name="Chofer Final", carrier=carrier)
    truck = Truck.create(domain="AA111BB", carrier=carrier)
    starch = Product.create(name="Fecula bolsa 25kg", unit="bolsas")
    flour = Product.create(name="Harina bolsa 10kg", unit="bolsas")

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": north_address,
                "observations": "Descargar por porton 2",
                "products": [
                    {"product": starch, "quantity": 120},
                    {"product": flour, "quantity": 80},
                ],
            },
            {
                "client": south_client,
                "delivery_address": south_address,
                "products": [{"product": starch, "quantity": 40}],
            },
        ],
        pallets=[],
        observations="Prioridad de despacho oficina.",
    )

    pdf_path = LoadOrderPrintService(current_user="admin").export_pdf(order, tmp_path)
    text = _pdf_text(pdf_path)

    assert "Cliente Norte" in text
    assert "Cliente Sur" in text
    assert "Fecula bolsa 25kg" in text
    assert "Harina bolsa 10kg" in text
    assert "160" in text
    assert "2" in text
    assert "Prioridad de despacho oficina." in text
    assert "Factura" not in text
    assert "Remito fiscal" not in text
    assert "F150" not in text


def test_pdf_marks_annulled_order_without_changing_status(db, tmp_path):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _order()
    annulled = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).annul(order, can_annul=True)

    pdf_path = LoadOrderPrintService(current_user="admin").export_pdf(annulled, tmp_path)
    text = _pdf_text(pdf_path)

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ANNULLED
    assert "ANULADA" in text
    assert "Estado: Anulada" in text


def test_pdf_uses_up_to_four_product_columns_and_sends_extra_products_to_detail(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte Articulos")
    driver = Driver.create(name="Chofer Articulos", carrier=carrier)
    truck = Truck.create(domain="ART123", carrier=carrier)
    client = Client.create(name="Cliente Articulos", cuit="30720000001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino articulos",
    )
    products = [
        Product.create(name=name, unit=unit)
        for name, unit in (
            ("Fecula 25kg", "bolsas"),
            ("Fecula 10kg", "bolsas"),
            ("Pack 1kg", "packs"),
            ("Almidon", "kg"),
            ("Producto extra", "cajas"),
        )
    ]
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {"product": product, "quantity": index * 10}
                    for index, product in enumerate(products, start=1)
                ],
            }
        ],
        pallets=[],
    )

    pdf_path = LoadOrderPrintService(current_user="admin").export_pdf(order, tmp_path)
    text = _pdf_text(pdf_path)

    assert "Fecula" in text
    assert "25kg" in text
    assert "10kg" in text
    assert "Pack 1kg" in text
    assert "Almidon" in text
    assert "Producto extra - 50 cajas" in text
    assert "Bolsas 25 kg" not in text
    assert "Bolsas 10 kg" not in text
    assert "Lote" in text
    assert "Elab." in text


def test_printing_again_regenerates_same_pdf_without_reprint_copy(db, tmp_path):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService

    order = _order()
    operations = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)
    issued = operations.issue(order)

    first_path = operations.print_order(issued)
    second_path = operations.print_order(issued)
    reloaded = LoadOrder.get_by_id(issued.id)
    text = _pdf_text(second_path)

    assert reloaded.status == LoadOrder.STATUS_ISSUED
    assert first_path == second_path
    assert second_path.name == "orden_carga_1.pdf"
    assert "Reimpresion" not in text


def test_print_service_exports_budget_pdf_for_client(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    client = Client.create(name="Cliente Presupuesto", cuit="30111111111", iva_condition="RI", descuento_porcentaje=5.0)
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12"
    )
    product = Product.create(name="Fecula Premium", unit="kg", precio_neto_base=20000.0, tipo_iva=iva)
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="BUDGET01", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 50}]}],
        pallets=[],
    )

    service = LoadOrderPrintService(current_user="admin")
    pdf_path = service.export_budget(order, client, tmp_path)
    text = _pdf_text(pdf_path)

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "PRESUPUESTO" in text
    assert "Cliente Presupuesto" in text
    assert "$ 1,000,000" in text or "1,000,000" in text
    assert "$ 50,000" in text or "50,000" in text


def test_print_service_exports_budgets_for_all_clients_in_order(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    client_a = Client.create(name="Cliente A Budget", cuit="30111111112", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a, address_type="entrega", province="Misiones", city="Posadas", address="Ruta A"
    )
    client_b = Client.create(name="Cliente B Budget", cuit="30111111113", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b, address_type="entrega", province="Misiones", city="Obera", address="Ruta B"
    )
    product = Product.create(name="Producto test", unit="kg")
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="BUDGET02", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[
            {"client": client_a, "delivery_address": address_a, "products": [{"product": product, "quantity": 10}]},
            {"client": client_b, "delivery_address": address_b, "products": [{"product": product, "quantity": 20}]},
        ],
        pallets=[],
    )

    service = LoadOrderPrintService(current_user="admin")
    paths = service.export_budgets(order, tmp_path)

    assert len(paths) == 2
    for p in paths:
        assert p.read_bytes().startswith(b"%PDF")
    names = [p.name for p in paths]
    assert any("Cliente_A_Budget" in n for n in names)
    assert any("Cliente_B_Budget" in n for n in names)


def test_print_service_exports_combined_budget_pdf_for_all_clients(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    client_a = Client.create(name="Cliente A Combined", cuit="30111111122", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a, address_type="entrega", province="Misiones", city="Posadas", address="Ruta A"
    )
    client_b = Client.create(name="Cliente B Combined", cuit="30111111123", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b, address_type="entrega", province="Misiones", city="Obera", address="Ruta B"
    )
    product_a = Product.create(name="Producto combinado A", unit="kg")
    product_b = Product.create(name="Producto combinado B", unit="bolsas")
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="BUDGET03", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[
            {"client": client_a, "delivery_address": address_a, "products": [{"product": product_a, "quantity": 10}]},
            {"client": client_b, "delivery_address": address_b, "products": [{"product": product_b, "quantity": 20}]},
        ],
        pallets=[],
    )

    service = LoadOrderPrintService(current_user="admin")
    path = service.export_combined_budget(order, tmp_path)
    text = _pdf_text(path)

    assert path.name == "presupuestos_orden_1.pdf"
    assert path.read_bytes().startswith(b"%PDF")
    assert "Cliente A Combined" in text
    assert "Producto combinado A" in text
    assert "Cliente B Combined" in text
    assert "Producto combinado B" in text

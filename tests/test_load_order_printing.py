from pathlib import Path


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


def test_print_service_exports_order_summary_and_combined_html(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _order()
    service = LoadOrderPrintService(current_user="admin")

    order_path = service.export_order(order, tmp_path)
    summary_path = service.export_summary(order, tmp_path)
    combined_path = service.export_combined(order, tmp_path, reprint=True)

    for path in (order_path, summary_path, combined_path):
        html = Path(path).read_text(encoding="utf-8")
        assert "Orden de carga Nro. 1" in html
        assert "Cliente FEMAG" in html
        assert "Juan Perez" in html
        assert "AB123CD" in html

    combined = Path(combined_path).read_text(encoding="utf-8")
    assert "Hoja resumen / sobre de carga" in combined
    assert "@page" in combined
    assert "Reimpresion" in combined
    assert AuditLog.select().where(AuditLog.action == "reimprimir").count() == 1


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

    html = Path(LoadOrderPrintService(current_user="admin").export_combined(order, tmp_path)).read_text(
        encoding="utf-8"
    )

    assert "Cabecera logística" in html
    assert "Detalle por cliente / destino" in html
    assert html.index("Cliente FEMAG") < html.index("Fecula")
    assert html.index("Cliente Sur") < html.index("Almidon")
    assert "Cliente cabecera" not in html


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

    html = Path(LoadOrderPrintService(current_user="admin").export_combined(order, tmp_path)).read_text(
        encoding="utf-8"
    )

    assert "<title>Orden de carga OC-000001</title>" in html
    assert "Documento logistico interno" in html
    assert "No fiscal" in html
    assert "Cliente / destino 1" in html
    assert "Cliente / destino 2" in html
    assert html.index("Cliente Norte") < html.index("Fecula bolsa 25kg")
    assert html.index("Cliente Sur") < html.rindex("Fecula bolsa 25kg")
    assert "Total destino: 200 bolsas" in html
    assert "Total destino: 40 bolsas" in html
    assert "Total general: 240 bolsas" in html
    assert "Prioridad de despacho oficina." in html
    assert "Factura" not in html
    assert "Remito fiscal" not in html
    assert "F150" not in html


def test_final_summary_envelope_is_compact_and_does_not_flatten_clients(db, tmp_path):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte Sobre")
    driver = Driver.create(name="Chofer Sobre", carrier=carrier)
    truck = Truck.create(domain="SB123CD", carrier=carrier)
    product = Product.create(name="Producto Sobre", unit="packs")
    destinations = []
    for index, name in enumerate(("Cliente A", "Cliente B"), start=1):
        client = Client.create(name=name, cuit=f"3072000000{index}", iva_condition="RI")
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city=f"Ciudad {index}",
            address=f"Destino {index}",
        )
        destinations.append(
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": index * 10}],
            }
        )
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=destinations,
        pallets=[],
    )

    summary = Path(LoadOrderPrintService(current_user="admin").export_summary(order, tmp_path)).read_text(
        encoding="utf-8"
    )

    assert "Hoja resumen / sobre de carga" in summary
    assert "Resumen para adjuntar al sobre de la orden" in summary
    assert "Cliente A - Destino 1, Ciudad 1" in summary
    assert "Cliente B - Destino 2, Ciudad 2" in summary
    assert "2 clientes / destinos" in summary
    assert "Total general: 30 packs" in summary
    assert "Cliente unico" not in summary


def test_reprint_html_marks_copy_and_preserves_issued_status(db, tmp_path):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService

    order = _order()
    operations = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)
    issued = operations.issue(order)

    reprint_path = operations.reprint_order(issued)
    reloaded = LoadOrder.get_by_id(issued.id)
    html = Path(reprint_path).read_text(encoding="utf-8")

    assert reloaded.status == LoadOrder.STATUS_ISSUED
    assert "Reimpresion operativa" in html
    assert "Copia para reimpresion" in html

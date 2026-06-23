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
    driver = Driver.create(name="Juan Perez")
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
        assert "Orden de despacho de fécula de mandioca" in html or "Orden de carga Nro. 1" in html
        assert "Cliente FEMAG" in html
        assert "Juan Perez" in html
        assert "AB123CD" in html
        assert "Vehículo limpio y apto" in html or "Veh�culo limpio y apto" in html

    combined = Path(combined_path).read_text(encoding="utf-8")
    assert "Hoja resumen / sobre de carga" in combined
    assert "@page" in combined
    assert "Reimpresión" in combined or "Reimpresi�n" in combined
    assert AuditLog.select().where(AuditLog.action == "reimprimir").count() == 1

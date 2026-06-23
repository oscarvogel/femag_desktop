from pathlib import Path


def _order():
    from app.models.masters import Carrier, Client, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    other_client = Client.create(name="Cliente Sur", cuit="30712345679", iva_condition="RI")
    carrier = Carrier.create(name="Transporte Norte")
    driver = Driver.create(name="Juan Perez")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    product = Product.create(name="Fecula", unit="bolsa")
    return LoadOrderService(current_user="admin").create_order(
        header_client_text="VARIOS",
        destination="Corrientes - Entre Rios - Buenos Aires",
        carrier=carrier,
        driver=driver,
        truck=truck,
        vehicle_clean_and_suitable=True,
        lines=[
            {
                "client": client,
                "recipient_text": "Graef Hermanos",
                "destination_text": "Corrientes",
                "product": product,
                "product_detail": "Fecula x 25 kg",
                "bags_25kg": 20,
                "bags_10kg": 5,
                "pack": 2,
                "pallet": 1,
                "lot_number": "L-001",
                "production_date": "2026-06-01",
            },
            {
                "client": other_client,
                "recipient_text": "Cliente Sur",
                "destination_text": "Buenos Aires",
                "product_detail": "Pack mixto",
                "bags_25kg": 10,
                "bags_10kg": 7,
                "pack": 8,
                "pallet": 2,
                "lot_number": "L-002",
                "production_date": "2026-06-02",
            },
        ],
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
        assert "Orden de despacho de fecula de mandioca" in html
        assert "VARIOS" in html
        assert "Corrientes - Entre Rios - Buenos Aires" in html
        assert "Graef Hermanos" in html
        assert "Cliente Sur" in html
        assert "Bolsas x 25 kg" in html
        assert "Bolsas x 10 kg" in html
        assert "L-001" in html
        assert "01/06/2026" in html
        assert "Totales" in html
        assert ">30<" in html
        assert ">12<" in html
        assert ">10<" in html
        assert ">3<" in html
        assert "Vehiculo limpio y apto" in html
        assert "Si" in html
        assert "Juan Perez" in html
        assert "AB123CD" in html
        assert "Firma del encargado de carga" in html

    combined = Path(combined_path).read_text(encoding="utf-8")
    assert "Hoja resumen / sobre de carga" in combined
    assert "@page" in combined
    assert "Reimpresion" in combined
    assert AuditLog.select().where(AuditLog.action == "reimprimir").count() == 1

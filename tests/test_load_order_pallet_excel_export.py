from openpyxl import load_workbook


def test_pallet_excel_matches_print_layout_and_keeps_mixed_pallet_cells_merged(db, tmp_path):
    from app.models.audit import AuditLog
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
    from app.services.load_order_pallet_excel_export_service import LoadOrderPalletExcelExportService
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente Excel", cuit="30700000123", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Excel",
    )
    carrier = Carrier.create(name="Transporte Excel")
    driver = Driver.create(name="Chofer Excel", carrier=carrier)
    truck = Truck.create(domain="XLSX123", carrier=carrier)
    nativa = Product.create(name="BOLSAS DE FECULA NATIVA", unit="UNIDAD")
    mezcla = Product.create(name="PACK FECULA X 1 KG", unit="UNIDAD")
    pallet_type = PalletType.create(type="Pallet Excel", measure="1x1", weight=0)
    order = LoadOrderService(current_user="excel").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {"product": nativa, "quantity": 550},
                    {"product": mezcla, "quantity": 20},
                ],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "pallet_type": pallet_type,
                "allocations": [
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": nativa,
                        "quantity": 10,
                    },
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": mezcla,
                        "quantity": 20,
                    },
                ],
            },
            *[
                {
                    "sequence": sequence,
                    "pallet_type": pallet_type,
                    "allocations": [
                        {
                            "client": client,
                            "delivery_address": address,
                            "product": nativa,
                            "quantity": 60,
                        }
                    ],
                }
                for sequence in range(5, 14)
            ],
        ],
    )

    target = LoadOrderPalletExcelExportService(current_user="excel").export(order, tmp_path)

    assert target.name == "orden_carga_1_armado_pallets.xlsx"
    workbook = load_workbook(target)
    sheet = workbook["Orden de despacho"]

    assert sheet["A1"].value == "ORDEN DE DESPACHO DE FECULA DE MANDIOCA"
    assert sheet["A2"].value == "Nro.: 0001"
    assert sheet["A4"].value == "QR de la orden"

    values = {
        (cell.row, cell.column): cell.value
        for row in sheet.iter_rows()
        for cell in row
        if cell.value is not None
    }
    text_values = [str(value) for value in values.values()]

    assert "1. DATOS DEL CLIENTE" in text_values
    assert "2. DETALLE DEL PRODUCTO A DESPACHAR" in text_values
    assert "3. DATOS DEL TRANSPORTE" in text_values
    assert "Cliente Excel" in text_values
    assert any("Misiones - Posadas - Ruta Excel" in value for value in text_values)
    assert "Transporte Excel" in text_values
    assert "XLSX123" in text_values
    assert "Chofer Excel" in text_values
    assert any(value.startswith("Observaciones:") for value in text_values)
    assert any(value.startswith("Firma del encargado de carga:") for value in text_values)

    header_row = next(
        row
        for row in range(1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "Producto / detalle"
    )
    assert [sheet.cell(header_row, column).value for column in range(1, 6)] == [
        "Producto / detalle",
        "Cantidad total",
        "Pallet",
        "Lote",
        "Elab.",
    ]

    mixed_start = next(
        row
        for row in range(header_row + 1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "BOLSAS DE FECULA NATIVA"
        and sheet.cell(row, 2).value == "10 UNIDADES"
    )
    assert sheet.cell(mixed_start, 3).value == "1"
    assert sheet.cell(mixed_start + 1, 1).value == "PACK FECULA X 1 KG"
    assert sheet.cell(mixed_start + 1, 3).value is None
    assert f"C{mixed_start}:C{mixed_start + 1}" in {
        str(merged) for merged in sheet.merged_cells.ranges
    }

    grouped_row = next(
        row
        for row in range(header_row + 1, sheet.max_row + 1)
        if sheet.cell(row, 1).value == "BOLSAS DE FECULA NATIVA"
        and sheet.cell(row, 2).value == "60 UNIDADES"
    )
    assert sheet.cell(grouped_row, 3).value == "9 pallets"

    assert sheet.page_setup.orientation == "portrait"
    assert sheet.print_area
    assert AuditLog.select().where(AuditLog.action == "exportar_excel_pallets").count() == 1

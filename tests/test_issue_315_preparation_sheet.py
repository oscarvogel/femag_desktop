def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


def test_regular_order_table_keeps_five_columns():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    service = ConsolidatedLoadOrderPrintService(current_user="issue315")
    block = {
        "destination": "CLIENTE - DESTINO",
        "consolidated_rows": [
            {
                "product": "FECULA X25KG",
                "unit": "BOLSA",
                "pallets": "1–2",
                "pallet_count": 2,
                "quantity": 120,
                "lote": "",
                "elab": "",
            }
        ],
    }

    table = service._destination_table(block)
    headers = [_plain_text(cell) for cell in table._cellvalues[0]]

    assert headers == ["Producto / detalle", "Cant. pallets", "Cantidad total", "Lote", "Elab."]


def test_consolidated_print_uses_single_page_base_builder():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService
    from app.services.load_order_print_service import LoadOrderPrintService

    assert ConsolidatedLoadOrderPrintService._build_pdf is LoadOrderPrintService._build_pdf

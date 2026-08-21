def _service():
    from app.services.rowspan_consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue315-rowspan")


def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


def _shared_pallet_block():
    products = [
        ("Fecula de maiz X 25KG", "BOLSA", 30),
        ("PACK 10 UNIDADES X 1 KG", "PACK", 50),
        ("BOLSAS DE FECULA NATIVA X 1/2KG PACK X 10", "PACK", 20),
        ("FECULA MAIZ X1/2KG PACK X 10", "PACK", 15),
    ]
    pallet_rows = [
        {"product": product, "unit": unit, "quantity": quantity, "lote": "", "elab": ""}
        for product, unit, quantity in products
    ]
    consolidated_rows = [
        {
            "product": product,
            "unit": unit,
            "pallets": "1",
            "pallet_count": 1,
            "quantity": quantity,
            "lote": "",
            "elab": "",
        }
        for product, unit, quantity in products
    ]
    return {
        "destination": "STRANGES LEONARDO Y STRANGES MAURICIO SH - ALSINA 1835",
        "pallet_blocks": [{"label": "1", "rows": pallet_rows}],
        "loose_block": None,
        "unassigned_block": None,
        "consolidated_rows": consolidated_rows,
    }


def test_regular_detail_rowspans_pallet_count_for_products_in_same_pallet():
    service = _service()
    table = service._destination_table(_shared_pallet_block())
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[2][1] == "1"
    assert rows[3][1] == ""
    assert rows[4][1] == ""
    assert rows[5][1] == ""
    assert (1, 2, 1, 5) in table._spanRanges


def test_preparation_sheet_rowspans_pallet_count_for_products_in_same_pallet():
    service = _service()
    table = service._preparation_destination_table(_shared_pallet_block())
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[2][2] == "1"
    assert rows[3][2] == ""
    assert rows[4][2] == ""
    assert rows[5][2] == ""
    assert (2, 2, 2, 5) in table._spanRanges

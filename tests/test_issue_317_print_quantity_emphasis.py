from reportlab.lib.enums import TA_CENTER


def _service():
    from app.services.rowspan_consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue317")


def _block():
    return {
        "destination": "CLIENTE - DESTINO",
        "pallet_blocks": [
            {
                "label": "1",
                "rows": [
                    {
                        "product": "BOL.FEC. NATIVA X25KG",
                        "unit": "BOLSA",
                        "quantity": 180,
                        "lote": "L-01",
                        "elab": "21/08/26",
                    }
                ],
            }
        ],
        "loose_block": None,
        "unassigned_block": None,
        "consolidated_rows": [
            {
                "product": "BOL.FEC. NATIVA X25KG",
                "unit": "BOLSA",
                "pallets": "1",
                "pallet_count": 1,
                "quantity": 180,
                "lote": "L-01",
                "elab": "21/08/26",
            }
        ],
    }


def _assert_emphasized(paragraph):
    assert paragraph.style.alignment == TA_CENTER
    assert paragraph.style.fontName == "Helvetica-Bold"
    assert paragraph.style.fontSize == 9


def test_regular_order_emphasizes_total_and_pallet_count_only():
    table = _service()._destination_table(_block())

    total = table._cellvalues[2][1]
    pallets = table._cellvalues[2][2]
    product = table._cellvalues[2][0]

    _assert_emphasized(total)
    _assert_emphasized(pallets)
    assert product.style.fontSize < total.style.fontSize
    assert product.style.fontName != "Helvetica-Bold"


def test_preparation_sheet_emphasizes_total_and_pallet_count_only():
    table = _service()._preparation_destination_table(_block())

    total = table._cellvalues[2][2]
    pallets = table._cellvalues[2][3]
    unit = table._cellvalues[2][1]

    _assert_emphasized(total)
    _assert_emphasized(pallets)
    assert unit.style.fontSize < total.style.fontSize
    assert unit.style.fontName != "Helvetica-Bold"

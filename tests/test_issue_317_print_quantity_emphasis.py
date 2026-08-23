from reportlab.lib.enums import TA_CENTER


def _service():
    from app.services.rowspan_consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue317")


def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


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


def test_regular_order_emphasizes_total_and_pallet_count_with_operational_labels():
    table = _service()._destination_table(_block())

    total = table._cellvalues[2][1]
    pallets = table._cellvalues[2][2]
    product = table._cellvalues[2][0]

    _assert_emphasized(total)
    _assert_emphasized(pallets)
    assert _plain_text(total) == "180 BOLSAS"
    assert _plain_text(pallets) == "1 pallet"
    assert product.style.fontSize < total.style.fontSize
    assert product.style.fontName != "Helvetica-Bold"


def test_preparation_sheet_keeps_unit_separate_and_labels_pallet_count():
    table = _service()._preparation_destination_table(_block())

    total = table._cellvalues[2][2]
    pallets = table._cellvalues[2][3]
    unit = table._cellvalues[2][1]

    _assert_emphasized(total)
    _assert_emphasized(pallets)
    assert _plain_text(unit) == "BOLSA"
    assert _plain_text(total) == "180"
    assert _plain_text(pallets) == "1 pallet"
    assert unit.style.fontSize < total.style.fontSize
    assert unit.style.fontName != "Helvetica-Bold"


def test_quantity_unit_pluralization_and_invariable_units():
    service = _service()

    assert service._quantity_with_unit(1, "BOLSA") == "1 BOLSA"
    assert service._quantity_with_unit(30, "BOLSA") == "30 BOLSAS"
    assert service._quantity_with_unit(1, "UNIDAD") == "1 UNIDAD"
    assert service._quantity_with_unit(50, "UNIDAD") == "50 UNIDADES"
    assert service._quantity_with_unit(50, "PACK") == "50 PACK"
    assert service._quantity_with_unit(125, "KG") == "125 KG"


def test_pallet_label_uses_singular_and_plural():
    service = _service()

    assert service._pallet_label("1") == "1 pallet"
    assert service._pallet_label("8") == "8 pallets"
    assert service._pallet_label("-") == "-"

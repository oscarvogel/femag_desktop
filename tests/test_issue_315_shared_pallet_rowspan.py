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


def test_regular_detail_places_total_before_pallets_and_rowspans_shared_pallet():
    service = _service()
    table = service._destination_table(_shared_pallet_block())
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == ["Producto / detalle", "Cantidad total", "Pallet/s", "Lote", "Elab."]
    assert rows[2][1] == "30 BOLSAS"
    assert rows[2][2] == "1"
    assert rows[3][2] == ""
    assert rows[4][2] == ""
    assert rows[5][2] == ""
    assert ("SPAN", (2, 2), (2, 5)) in table._spanCmds
    assert table._cellvalues[2][1].style.alignment == 1
    assert table._cellvalues[2][2].style.alignment == 1


def test_preparation_sheet_places_total_before_pallets_and_rowspans_shared_pallet():
    service = _service()
    table = service._preparation_destination_table(_shared_pallet_block())
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == [
        "Producto / detalle",
        "Unidad",
        "Cantidad total",
        "Pallet/s",
        "Lote",
        "Elab.",
    ]
    assert rows[2][2] == "30"
    assert rows[2][3] == "1"
    assert rows[3][3] == ""
    assert rows[4][3] == ""
    assert rows[5][3] == ""
    assert ("SPAN", (3, 2), (3, 5)) in table._spanCmds
    assert table._cellvalues[2][2].style.alignment == 1
    assert table._cellvalues[2][3].style.alignment == 1


def test_pallet_display_falls_back_to_consolidated_value_when_signature_is_unavailable():
    service = _service()
    block = {
        "destination": "INDUS. FRIGORIFICAS RECREO SA - S/N - SANTA FE",
        "pallet_blocks": [],
        "loose_block": None,
        "unassigned_block": None,
        "consolidated_rows": [
            {
                "product": "BOL.FEC. NATIVA X25KG",
                "unit": "BOLSA",
                "pallets": "1-8",
                "pallet_count": 8,
                "quantity": 480,
                "lote": "",
                "elab": "",
            }
        ],
    }

    table = service._destination_table(block)
    prep_table = service._preparation_destination_table(block)

    assert _plain_text(table._cellvalues[2][1]) == "480 BOLSAS"
    assert _plain_text(table._cellvalues[2][2]) == "1-8"
    assert _plain_text(prep_table._cellvalues[2][2]) == "480"
    assert _plain_text(prep_table._cellvalues[2][3]) == "1-8"


def test_issue_413_shared_physical_pallet_is_not_double_counted_visually():
    service = _service()
    block = {
        "destination": "GNESETTI SOFIA - ESPAÑA 3757",
        "pallet_blocks": [
            {
                "label": "1",
                "rows": [
                    {
                        "product": "BOLSAS DE FECULA NATIVA",
                        "unit": "UNIDAD",
                        "quantity": 60,
                        "lote": "47",
                        "elab": "31/08/26",
                    }
                ],
            },
            {
                "label": "2",
                "rows": [
                    {
                        "product": "BOLSAS DE FECULA NATIVA",
                        "unit": "UNIDAD",
                        "quantity": 30,
                        "lote": "47",
                        "elab": "31/08/26",
                    },
                    {
                        "product": "BOLSAS FECULA X 10KG.",
                        "unit": "UNIDAD",
                        "quantity": 75,
                        "lote": "43",
                        "elab": "31/08/26",
                    },
                ],
            },
        ],
        "loose_block": None,
        "unassigned_block": None,
    }
    block["consolidated_rows"] = service._consolidate_rows(block)

    table = service._destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == ["Producto / detalle", "Cantidad total", "Pallet/s", "Lote", "Elab."]
    assert rows[2][1] == "90 UNIDADES"
    assert rows[2][2] == "1–2"
    assert rows[3][1] == "75 UNIDADES"
    assert rows[3][2] == "2"
    assert ("SPAN", (2, 2), (2, 3)) not in table._spanCmds

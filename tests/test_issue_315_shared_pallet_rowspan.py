def _service():
    from app.services.rowspan_consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue473-physical-pallets")


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
    return {
        "destination": "STRANGES LEONARDO Y STRANGES MAURICIO SH - ALSINA 1835",
        "pallet_blocks": [{"label": "1", "rows": pallet_rows}],
        "loose_block": None,
        "unassigned_block": None,
    }


def test_regular_detail_prints_physical_pallet_and_rowspans_all_its_articles():
    service = _service()
    table = service._destination_table(_shared_pallet_block())
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == ["Producto / detalle", "Cantidad total", "Pallet", "Lote", "Elab."]
    assert rows[2][1] == "30 BOLSAS"
    assert rows[2][2] == "1"
    assert rows[3][2] == ""
    assert rows[4][2] == ""
    assert rows[5][2] == ""
    assert ("SPAN", (2, 2), (2, 5)) in table._spanCmds
    assert table._cellvalues[2][1].style.alignment == 1
    assert table._cellvalues[2][2].style.alignment == 1


def test_identical_single_product_pallets_are_grouped_with_total_quantity():
    service = _service()
    block = {
        "destination": "GNESETTI SOFIA - ESPAÑA 3757",
        "pallet_blocks": [
            {
                "label": str(sequence),
                "rows": [
                    {
                        "product": "BOLSAS DE FECULA NATIVA",
                        "unit": "UNIDAD",
                        "quantity": 60,
                        "lote": "47",
                        "elab": "31/08/26",
                    }
                ],
            }
            for sequence in range(5, 14)
        ],
        "loose_block": None,
        "unassigned_block": None,
    }
    block["consolidated_rows"] = service._consolidate_rows(block)

    table = service._destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[2][0] == "BOLSAS DE FECULA NATIVA"
    assert rows[2][1] == "540 UNIDADES"
    assert rows[2][2] == "9 pallets"
    assert len(rows) == 3


def test_grouped_single_product_pallets_print_total_for_reported_cases():
    service = _service()

    def grouped_row(pallet_count):
        block = {
            "destination": "CLIENTE PRUEBA - DESTINO",
            "pallet_blocks": [
                {
                    "label": str(sequence),
                    "rows": [
                        {
                            "product": "BOLSAS DE FECULA NATIVA",
                            "unit": "UNIDAD",
                            "quantity": 60,
                            "lote": "",
                            "elab": "",
                        }
                    ],
                }
                for sequence in range(1, pallet_count + 1)
            ],
            "loose_block": None,
            "unassigned_block": None,
        }
        table = service._destination_table(block)
        return [_plain_text(cell) for cell in table._cellvalues[2]]

    assert grouped_row(19)[1:3] == ["1140 UNIDADES", "19 pallets"]
    assert grouped_row(2)[1:3] == ["120 UNIDADES", "2 pallets"]


def test_issue_473_pallet_with_three_articles_prints_one_pallet_block():
    service = _service()
    block = {
        "destination": "CLIENTE PRUEBA - DESTINO",
        "pallet_blocks": [
            {
                "label": "2",
                "rows": [
                    {"product": "PRODUCTO A", "unit": "UNIDAD", "quantity": 10, "lote": "", "elab": ""},
                    {"product": "PRODUCTO B", "unit": "UNIDAD", "quantity": 20, "lote": "", "elab": ""},
                    {"product": "PRODUCTO C", "unit": "UNIDAD", "quantity": 30, "lote": "", "elab": ""},
                ],
            }
        ],
        "loose_block": None,
        "unassigned_block": None,
    }

    table = service._destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert [rows[index][0] for index in (2, 3, 4)] == ["PRODUCTO A", "PRODUCTO B", "PRODUCTO C"]
    assert rows[2][2] == "2"
    assert rows[3][2] == ""
    assert rows[4][2] == ""
    assert ("SPAN", (2, 2), (2, 4)) in table._spanCmds


def test_issue_473_loose_merchandise_stays_separate_from_pallets():
    service = _service()
    block = {
        "destination": "CLIENTE PRUEBA - DESTINO",
        "pallet_blocks": [
            {
                "label": "1",
                "rows": [
                    {"product": "PRODUCTO A", "unit": "BOLSA", "quantity": 60, "lote": "", "elab": ""}
                ],
            }
        ],
        "loose_block": {
            "label": "SUELTO",
            "rows": [
                {"product": "PRODUCTO B", "unit": "UNIDAD", "quantity": 5, "lote": "", "elab": ""}
            ],
        },
        "unassigned_block": None,
    }

    table = service._destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[2][2] == "1 pallet"
    assert rows[3][2] == "SUELTO"

def _service():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return object.__new__(ConsolidatedLoadOrderPrintService)


def test_compacts_consecutive_and_discontinuous_pallet_ranges():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    assert ConsolidatedLoadOrderPrintService._compact_ranges([3, 4, 5, 6, 7]) == "3–7"
    assert ConsolidatedLoadOrderPrintService._compact_ranges([3, 4, 5, 8, 9, 12]) == "3–5, 8–9, 12"
    assert ConsolidatedLoadOrderPrintService._compact_ranges([20]) == "20"


def test_same_product_on_many_pallets_becomes_one_row_with_total():
    service = _service()
    block = {
        "destination": "CARDOZO MAURICIO - CORRIENTES",
        "pallet_blocks": [
            {
                "label": str(sequence),
                "rows": [
                    {
                        "quantity": 60.0,
                        "product": "BOL.FEC. NATIVA X25KG",
                        "lote": "-",
                        "elab": "-",
                    }
                ],
            }
            for sequence in range(3, 17)
        ],
        "loose_block": None,
        "unassigned_block": None,
    }

    rows = service._consolidate_rows(block)

    assert rows == [
        {
            "product": "BOL.FEC. NATIVA X25KG",
            "pallets": "3–16",
            "pallet_count": 14,
            "quantity": 840.0,
            "lote": "",
            "elab": "",
        }
    ]

    service = service.__class__(current_user="test")
    table = service._destination_table(block)
    # Layout #308: Producto | Cant. pallets | Cantidad total | Lote | Elab.
    assert len(table._cellvalues[2]) == 5
    assert table._cellvalues[2][3] == ""
    assert table._cellvalues[2][4] == ""


def test_heterogeneous_pallet_quantities_keep_per_pallet_information():
    service = _service()
    block = {
        "destination": "CLIENTE",
        "pallet_blocks": [
            {
                "label": str(sequence),
                "rows": [{"quantity": 60.0, "product": "NATIVA", "lote": "L1", "elab": "-"}],
            }
            for sequence in range(3, 16)
        ]
        + [
            {
                "label": "16",
                "rows": [{"quantity": 50.0, "product": "NATIVA", "lote": "L1", "elab": "-"}],
            }
        ],
        "loose_block": None,
        "unassigned_block": None,
    }

    row = service._consolidate_rows(block)[0]

    assert row["pallets"] == "3–15 (60 c/u) · 16 (50 c/u)"
    assert row["pallet_count"] == 14
    assert row["quantity"] == 830.0
    assert row["lote"] == "L1"
    assert row["elab"] == ""


def test_loose_merchandise_is_visible_without_counting_as_pallet():
    service = _service()
    block = {
        "destination": "CLIENTE",
        "pallet_blocks": [],
        "loose_block": {
            "label": "SUELTO",
            "rows": [{"quantity": 5.0, "product": "MODIFICADA X25KG", "lote": "-", "elab": "-"}],
        },
        "unassigned_block": None,
    }

    row = service._consolidate_rows(block)[0]

    assert row["pallets"] == "Suelto (5)"
    assert row["pallet_count"] == 0
    assert row["quantity"] == 5.0
    assert row["lote"] == ""
    assert row["elab"] == ""


def test_operation_service_uses_consolidated_printer():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService
    from app.services.load_order_operation_service import LoadOrderOperationService

    names = LoadOrderOperationService.__init__.__code__.co_names
    assert "ConsolidatedLoadOrderPrintService" in names
    assert ConsolidatedLoadOrderPrintService.__name__ == "ConsolidatedLoadOrderPrintService"

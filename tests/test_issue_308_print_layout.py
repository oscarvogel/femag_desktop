from types import SimpleNamespace

from reportlab.platypus import KeepTogether, Spacer


def _service():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    return ConsolidatedLoadOrderPrintService(current_user="issue308")


def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


def test_destination_table_omits_pallet_number_column():
    service = _service()
    block = {
        "destination": "CLIENTE - DESTINO",
        "consolidated_rows": [
            {
                "product": "FECULA X25KG",
                "pallets": "1–6",
                "pallet_count": 6,
                "quantity": 360,
                "lote": "",
                "elab": "",
            }
        ],
        "pallet_blocks": [],
        "loose_block": None,
        "unassigned_block": None,
    }

    table = service._destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == ["Producto / detalle", "Cant. pallets", "Cantidad total", "Lote", "Elab."]
    assert len(rows[0]) == 5
    assert "Pallets" not in rows[0]
    assert rows[2][1] == "6"
    assert rows[2][2] == "360"
    assert "1–6" not in rows[2]


def test_detail_flowables_add_spacing_between_destinations(monkeypatch):
    service = _service()
    blocks = [
        {"destination": "CLIENTE A", "consolidated_rows": []},
        {"destination": "CLIENTE B", "consolidated_rows": []},
    ]

    monkeypatch.setattr(service, "_detail_blocks", lambda order: blocks)
    monkeypatch.setattr(service, "_destination_table", lambda block: SimpleNamespace(block=block))
    monkeypatch.setattr(service, "_totals_table", lambda order, blocks: SimpleNamespace(kind="totals"))

    flowables = service._detail_flowables(SimpleNamespace())

    assert isinstance(flowables[0], KeepTogether)
    assert isinstance(flowables[1], Spacer)
    assert flowables[1].height > 0
    assert isinstance(flowables[2], KeepTogether)
    # Se conserva además el espacio previo a los totales.
    assert isinstance(flowables[3], Spacer)


def test_loose_merchandise_does_not_increase_pallet_count():
    service = _service()
    block = {
        "pallet_blocks": [
            {"label": "1", "rows": [{"product": "FECULA", "quantity": 60, "lote": "", "elab": ""}]},
        ],
        "loose_block": {
            "label": "SUELTO",
            "rows": [{"product": "FECULA", "quantity": 5, "lote": "", "elab": ""}],
        },
        "unassigned_block": None,
    }

    rows = service._consolidate_rows(block)

    assert rows[0]["pallet_count"] == 1
    assert rows[0]["quantity"] == 65

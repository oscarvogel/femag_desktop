from pathlib import Path
from types import SimpleNamespace

from reportlab.platypus import PageBreak, Spacer


def _plain_text(value):
    return value.getPlainText() if hasattr(value, "getPlainText") else str(value)


def test_preparation_table_adds_product_unit_column():
    from app.services.consolidated_load_order_print_service import ConsolidatedLoadOrderPrintService

    service = ConsolidatedLoadOrderPrintService(current_user="issue315")
    block = {
        "destination": "CARDOZO MAURICIO - CORRIENTES",
        "consolidated_rows": [
            {
                "product": "BOL.FEC. NATIVA X25KG",
                "unit": "BOLSA",
                "pallets": "3–5",
                "pallet_count": 3,
                "quantity": 180,
                "lote": "L-01",
                "elab": "21/08/26",
            }
        ],
    }

    table = service._preparation_destination_table(block)
    rows = [[_plain_text(cell) for cell in row] for row in table._cellvalues]

    assert rows[0] == [
        "Producto / detalle",
        "Unidad",
        "Cant. pallets",
        "Cantidad total",
        "Lote",
        "Elab.",
    ]
    assert rows[2][0] == "BOL.FEC. NATIVA X25KG"
    assert rows[2][1] == "BOLSA"
    assert rows[2][2] == "3"
    assert rows[2][3] == "180"


def test_regular_order_table_keeps_existing_five_columns():
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


def test_build_pdf_appends_preparation_page_after_order(monkeypatch, tmp_path):
    import app.services.consolidated_load_order_print_service as module

    captured = {}

    class FakeDoc:
        def __init__(self, *args, **kwargs):
            captured["doc_args"] = args
            captured["doc_kwargs"] = kwargs

        def build(self, story):
            captured["story"] = story

    monkeypatch.setattr(module, "SimpleDocTemplate", FakeDoc)

    service = module.ConsolidatedLoadOrderPrintService(current_user="issue315")
    spacer = lambda: Spacer(1, 1)
    monkeypatch.setattr(service, "_header_table", lambda order: spacer())
    monkeypatch.setattr(service, "_client_table", lambda order: spacer())
    monkeypatch.setattr(service, "_detail_flowables", lambda order: [spacer()])
    monkeypatch.setattr(service, "_transport_table", lambda order: spacer())
    monkeypatch.setattr(service, "_observations", lambda order: spacer())
    monkeypatch.setattr(service, "_preparation_flowables", lambda order: [spacer()])

    order = SimpleNamespace(order_number=315, status="emitida")
    service._build_pdf(order, Path(tmp_path) / "orden.pdf")

    story = captured["story"]
    page_break_indexes = [index for index, item in enumerate(story) if isinstance(item, PageBreak)]

    assert len(page_break_indexes) == 1
    break_index = page_break_indexes[0]
    assert any(
        getattr(item, "getPlainText", lambda: "")() == "2. DETALLE DEL PRODUCTO A DESPACHAR"
        for item in story[break_index + 1 :]
    )

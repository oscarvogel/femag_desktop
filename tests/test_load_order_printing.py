from load_order_printing_cases import *
import load_order_printing_cases as _cases


def test_print_service_exports_load_order_pdf_with_real_format_fields(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.load_order_print_service import LoadOrderPrintService

    order = _cases._order()
    service = LoadOrderPrintService(current_user="admin")

    pdf_path = service.export_pdf(order, tmp_path)
    text = _cases._pdf_text(pdf_path)

    assert pdf_path.name == "orden_carga_1.pdf"
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert "GRAEF HERMANOS S.R.L." not in text
    assert "ORDEN DE DESPACHO DE FECULA DE MANDIOCA" in text
    assert "Nro.: 0001" in text
    assert "1. DATOS DEL CLIENTE" in text
    assert "Cliente FEMAG" in text
    assert "Ruta 12" in text
    assert "2. DETALLE DEL PRODUCTO A DESPACHAR" in text
    assert "Fecula" in text
    assert "1000" in text
    assert "3. DATOS DEL TRANSPORTE" in text
    assert "Transporte Norte" in text
    assert "Juan Perez" in text
    assert "AB123CD" in text
    assert "TOTAL MERCADERIA:" in text
    assert "2.500 kg" in text
    assert "Imprimir con hoja resumen" in text
    assert "Firma del encargado de carga" in text
    assert AuditLog.select().where(AuditLog.action == "imprimir").count() == 1


def test_detail_rows_leave_client_lote_and_elab_cells_blank_for_depot_completion():
    from app.services.load_order_print_service import LoadOrderPrintService

    service = LoadOrderPrintService(current_user="admin")
    table = service._destination_table(
        {
            "destination": "CLIENTE - DESTINO",
            "pallet_blocks": [
                {
                    "label": "13",
                    "rows": [
                        {
                            "quantity": 60,
                            "product": "BOL.FEC. NATIVA X25KG",
                            "lote": "LOTE-INTERNO",
                            "elab": "18/08/26",
                        }
                    ],
                }
            ],
            "loose_block": None,
            "unassigned_block": None,
        }
    )

    detail_row = table._cellvalues[2]
    assert detail_row[0] == ""
    assert detail_row[4] == ""
    assert detail_row[5] == ""


def test_company_name_is_omitted_from_budget_prints(db, tmp_path):
    from app.services.load_order_print_service import LoadOrderPrintService

    order, client = _cases._budget_order([("Producto presupuesto", 21.0, 100.0, 10)])
    service = LoadOrderPrintService(current_user="admin")

    individual = service.export_budget(order, client, tmp_path)
    combined = service.export_combined_budget(order, tmp_path)

    assert "GRAEF HERMANOS S.R.L." not in _cases._pdf_text(individual)
    assert "GRAEF HERMANOS S.R.L." not in _cases._pdf_text(combined)

from pypdf import PdfReader


def test_remittance_pdf_is_non_fiscal_and_audited(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.remittance_print_service import RemittancePrintService
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    remittance = RemittanceService(current_user="admin").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        products=[{"product": data["product"], "quantity": 25}],
    )

    target = RemittancePrintService(current_user="admin").export_pdf(remittance, tmp_path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(target)).pages)

    assert target.name == "remito_REM-00000001.pdf"
    assert "DOCUMENTO NO FISCAL" in text
    assert "BORRADOR" in text
    assert "Fecula de mandioca" in text
    assert AuditLog.select().where(AuditLog.action == "imprimir").exists()

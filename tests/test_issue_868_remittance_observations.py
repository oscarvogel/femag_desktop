import pytest
from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.services.remittance_print_service import MM, RemittancePrintService
from app.services.remittance_service import RemittanceService
from tests.conftest import _master_data


def test_observation_is_printed_from_saved_remittance_in_both_pdfs(db, tmp_path):
    data = _master_data()
    service = RemittanceService("test")
    remittance = service.create_manual(
        client=data["client"], delivery_address=data["address"],
        carrier=data["carrier"], driver=data["driver"], truck=data["truck"],
        observations="Orden de compra 12345", items=[{"product": data["product"], "quantity": 1}],
    )
    remittance.status = remittance.STATUS_ISSUED
    remittance.save()
    printer = RemittancePrintService(current_user="test")
    for export in (printer.export_preview, printer.export_preprinted):
        path = export(remittance, tmp_path / f"{export.__name__}.pdf")
        assert "Observaciones: Orden de compra 12345" in PdfReader(path).pages[0].extract_text()


def test_observation_fits_between_detail_and_transport_and_rejects_overflow(db):
    data = _master_data()
    remittance = RemittanceService("test").create_manual(
        client=data["client"], delivery_address=data["address"],
        observations="compra " * 30, items=[{"product": data["product"], "quantity": 1}],
    )
    printer = RemittancePrintService(current_user="test")
    lines = printer._observation_lines(remittance)
    assert len(lines) > 1
    assert printer.template.first_detail_y - 15 * printer.template.detail_step > printer.template.observations_y
    assert printer.template.observations_y - (len(lines) - 1) * printer.template.observations_step > printer.template.carrier_y
    assert all(stringWidth(line, "Helvetica", 9) <= printer.template.observations_width * MM for line in lines)
    remittance.observations = "compra " * 300
    with pytest.raises(ValueError, match="demasiado larga"):
        printer._validated_items(remittance)
    remittance.observations = None
    assert printer._observation_lines(remittance) == []

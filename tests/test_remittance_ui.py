from pathlib import Path


def test_remittance_page_exposes_operational_actions(db, tmp_path):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.remittances import RemittancesPage

    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(current_user="ui_remittances", output_dir=tmp_path)
    app.processEvents()

    for object_name in (
        "newRemittanceButton",
        "newRemittanceFromOrderButton",
        "editRemittanceButton",
        "issueRemittanceButton",
        "printRemittanceButton",
        "remittanceCalibrationButton",
    ):
        button = page.findChild(QPushButton, object_name)
        assert button is not None
        assert button.isEnabled()

    assert page.table.columnCount() == 7


def test_calibration_pdf_is_generated(db, tmp_path):
    from app.services.remittance_print_service import RemittancePrintService

    output = tmp_path / "calibracion.pdf"
    result = RemittancePrintService(current_user="ui_remittances").export_calibration(output)

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_preprinted_pdf_only_requires_issued_remittance(db, tmp_path):
    import pytest

    from app.services.remittance_print_service import RemittancePrintService
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    service = RemittanceService(current_user="ui_remittances")
    remittance = service.create_manual(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        physical_point_of_sale="0001",
        physical_number="00010678",
        items=[
            {
                "product": data["product"],
                "quantity": 760,
                "printed_description": "BOL FECULA 2° CALIDAD",
            }
        ],
    )
    printer = RemittancePrintService(current_user="ui_remittances")

    with pytest.raises(ValueError, match="emitidos"):
        printer.export_preprinted(remittance, tmp_path / "draft.pdf")

    emitted = service.issue(remittance)
    output = printer.export_preprinted(emitted, tmp_path / "emitido.pdf")

    assert isinstance(output, Path)
    assert output.exists()
    assert output.stat().st_size > 0

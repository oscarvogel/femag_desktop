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


def test_preview_pdf_is_generated_for_draft_and_is_audited(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.remittance_print_service import RemittancePrintService
    from app.services.remittance_service import RemittanceService
    from tests.conftest import _master_data

    data = _master_data()
    remittance = RemittanceService(current_user="ui_preview").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        truck=data["truck"],
        driver=data["driver"],
        items=[
            {
                "product": data["product"],
                "quantity": 760,
                "printed_description": "BOL FECULA 2° CALIDAD",
            }
        ],
    )

    output = tmp_path / "preview_no_fiscal.pdf"
    result = RemittancePrintService(current_user="ui_preview").export_preview(remittance, output)

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0
    audit = AuditLog.select().where(AuditLog.record_ref == f"Remittance:{remittance.id}").order_by(AuditLog.id.desc()).first()
    assert audit.action == "vista previa"
    assert audit.new_value["mode"] == "preview_no_fiscal"


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


def test_sidebar_opens_real_remittances_page(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.remittances import RemittancesPage

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="ui_remittance_sidebar", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    assert "remittances" in window._route_indexes
    remittance_row = next(
        row
        for row in range(window.nav.count())
        if window.nav.item(row).text().strip() == "Remitos"
    )
    item = window.nav.item(remittance_row)
    assert item.data(Qt.UserRole) == "remittances"

    window.nav.setCurrentRow(remittance_row)
    app.processEvents()

    assert window._current_route == "remittances"
    assert isinstance(window.stack.currentWidget(), RemittancesPage)

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
        "previewRemittanceButton",
        "printRemittanceButton",
        "annulRemittanceButton",
        "remittanceCalibrationButton",
    ):
        button = page.findChild(QPushButton, object_name)
        assert button is not None
        assert button.isEnabled()

    assert page.table.columnCount() == 7


def test_manual_dialog_exposes_transport_and_observations(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QGroupBox, QLineEdit

    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    data = _master_data()
    app = QApplication.instance() or QApplication([])
    dialog = RemittanceDialog(current_user="ui_remittances")
    app.processEvents()

    assert dialog.findChild(QComboBox, "remittanceCarrierInput").findData(data["carrier"].id) >= 0
    assert dialog.findChild(QComboBox, "remittanceTruckInput").findData(data["truck"].id) >= 0
    assert dialog.findChild(QComboBox, "remittanceDriverInput").findData(data["driver"].id) >= 0
    assert dialog.findChild(QLineEdit, "remittanceObservationsInput") is not None
    assert dialog.findChild(QGroupBox, "remittanceHeaderGroup") is not None
    assert dialog.items.minimumHeight() == 280
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons.button(QDialogButtonBox.Save).text() == "Guardar"
    assert buttons.button(QDialogButtonBox.Cancel).text() == "Cancelar"


def test_manual_dialog_previews_default_series_without_consuming_number(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit

    from app.models.remittances import RemittanceSeries
    from app.services.remittance_service import RemittanceSeriesService
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    _master_data()
    series = RemittanceSeriesService("ui_series").save(
        name="Talonario UI",
        point_of_sale="1",
        next_number=10678,
        is_default=True,
    )
    app = QApplication.instance() or QApplication([])
    dialog = RemittanceDialog(current_user="ui_series")
    app.processEvents()

    selector = dialog.findChild(QComboBox, "remittanceSeriesInput")
    preview = dialog.findChild(QLineEdit, "remittanceNumberPreview")
    assert selector.currentData() == series.id
    assert preview.isReadOnly()
    assert preview.text() == "0001-00010678 (se asigna al emitir)"
    assert RemittanceSeries.get_by_id(series.id).next_number == 10678


def test_series_configuration_page_lists_numbering_and_actions(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.services.remittance_service import RemittanceSeriesService
    from app.ui.remittances import RemittanceSeriesPage

    RemittanceSeriesService("ui_series").save(
        name="Talonario configuración",
        point_of_sale="0003",
        next_number=45,
        end_number=100,
        is_default=True,
    )
    app = QApplication.instance() or QApplication([])
    page = RemittanceSeriesPage(current_user="ui_series")
    app.processEvents()

    for object_name in (
        "newRemittanceSeriesButton",
        "editRemittanceSeriesButton",
        "skipRemittanceSeriesNumberButton",
    ):
        assert page.findChild(QPushButton, object_name) is not None
    assert page.table.rowCount() == 1
    assert page.table.item(0, 2).text() == "0003"
    assert page.table.item(0, 3).text() == "00000045"


def test_manual_dialog_persists_transport_and_observations(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.remittances import Remittance
    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    data = _master_data()
    app = QApplication.instance() or QApplication([])
    dialog = RemittanceDialog(current_user="ui_remittances")
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(data["client"].id))
    dialog.address_combo.setCurrentIndex(dialog.address_combo.findData(data["address"].id))
    dialog.carrier_combo.setCurrentIndex(dialog.carrier_combo.findData(data["carrier"].id))
    dialog.truck_combo.setCurrentIndex(dialog.truck_combo.findData(data["truck"].id))
    dialog.driver_combo.setCurrentIndex(dialog.driver_combo.findData(data["driver"].id))
    dialog.items.cellWidget(0, 0).setCurrentIndex(
        dialog.items.cellWidget(0, 0).findData(data["product"].id)
    )
    dialog.items.cellWidget(0, 1).setText("25")
    dialog.items.cellWidget(0, 2).setText("Producto de prueba")
    dialog.observations_input.setText("Entregar por portón lateral")

    dialog._save()
    app.processEvents()

    remittance = Remittance.get()
    assert remittance.carrier_id == data["carrier"].id
    assert remittance.truck_id == data["truck"].id
    assert remittance.driver_id == data["driver"].id
    assert remittance.observations == "Entregar por portón lateral"


def test_detail_quantity_and_description_are_direct_editors(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit

    from app.ui.remittances import RemittanceDialog
    from tests.conftest import _master_data

    _master_data()
    app = QApplication.instance() or QApplication([])
    dialog = RemittanceDialog(current_user="ui_direct_detail")
    app.processEvents()

    quantity = dialog.items.cellWidget(0, 1)
    description = dialog.items.cellWidget(0, 2)
    assert isinstance(quantity, QLineEdit)
    assert isinstance(description, QLineEdit)
    assert quantity.validator() is not None
    quantity.setText("12,5")
    description.setText("Producto cargado con un clic")
    assert quantity.text() == "12,5"
    assert description.text() == "Producto cargado con un clic"


def test_page_preview_action_generates_selected_draft_pdf(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.services.remittance_service import RemittanceService
    from app.ui.remittances import RemittancesPage
    from tests.conftest import _master_data

    data = _master_data()
    remittance = RemittanceService("ui_preview_action").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        items=[{"product": data["product"], "quantity": 1, "printed_description": "Producto"}],
    )
    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(current_user="ui_preview_action", output_dir=tmp_path)
    page.table.selectRow(0)
    opened = []
    monkeypatch.setattr(page, "_open_pdf", opened.append)

    page._preview_selected()

    expected = tmp_path / f"vista_previa_{remittance.remittance_number.replace('-', '_')}.pdf"
    assert opened == [expected]
    assert expected.exists()


def test_page_annul_action_requires_reason_and_refreshes_state(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.remittances import Remittance
    from app.services.remittance_service import RemittanceService
    from app.ui import remittances as remittances_ui
    from tests.conftest import _master_data

    data = _master_data()
    remittance = RemittanceService("ui_annul_action").create_manual(
        client=data["client"],
        delivery_address=data["address"],
        items=[{"product": data["product"], "quantity": 1, "printed_description": "Producto"}],
    )
    app = QApplication.instance() or QApplication([])
    page = remittances_ui.RemittancesPage(current_user="ui_annul_action", output_dir=tmp_path)
    page.table.selectRow(0)
    monkeypatch.setattr(
        remittances_ui.QInputDialog,
        "getMultiLineText",
        lambda *_args, **_kwargs: ("Formulario dañado", True),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    page._annul_selected()

    updated = Remittance.get_by_id(remittance.id)
    assert updated.status == Remittance.STATUS_ANNULLED
    assert updated.annulment_reason == "Formulario dañado"


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
    window._navigate_to_route("remittances")
    app.processEvents()
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

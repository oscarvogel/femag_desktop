import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _admin_window(username: str):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username=username, password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    return app, window


def test_legacy_dbf_import_page_is_reachable_from_sidebar(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QLabel, QLineEdit, QListWidget, QPushButton

    app, window = _admin_window("admin_import_ui")
    nav = window.findChild(QListWidget, "sidebar")
    assert nav is not None

    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()

    import_row = None
    for row in range(nav.count()):
        item = nav.item(row)
        if item.text().strip() == "Importación DBF":
            import_row = row
            assert item.data(Qt.UserRole) == "legacy_dbf_import"
            break
    assert import_row is not None

    assert window.stack.currentIndex() == window._route_indexes["legacy_dbf_import"]
    assert window.findChild(QLabel, "legacyDbfImportTitle") is not None
    assert window.findChild(QLineEdit, "dbfClientsPathInput") is not None
    assert window.findChild(QLineEdit, "dbfCarriersPathInput") is not None
    assert window.findChild(QPushButton, "runLegacyDbfImportButton") is not None


def test_legacy_dbf_import_page_runs_importer_and_shows_summary(db, monkeypatch):
    from PyQt5.QtWidgets import QLabel, QLineEdit, QPushButton, QTableWidget

    from app.ui import desktop_app

    calls = []

    class FakeImporter:
        def import_dbf_files(self, paths_by_entity, *, source_system, encoding):
            calls.append((paths_by_entity, source_system, encoding))
            return {
                "clients": {"created": 2, "updated": 1, "skipped": 0, "errors": []},
                "carriers": {"created": 1, "updated": 0, "skipped": 0, "errors": []},
                "drivers": {
                    "created": 1,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [],
                    "warnings": [{"code": "carrier_not_found", "source_id": "0015"}],
                },
                "trucks": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
                "products": {"created": 3, "updated": 0, "skipped": 0, "errors": []},
            }

    monkeypatch.setattr(desktop_app, "LegacyDbfMasterImporter", FakeImporter)

    app, window = _admin_window("admin_import_run_ui")
    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()

    window.findChild(QLineEdit, "dbfClientsPathInput").setText(r"C:\legacy\clientes.dbf")
    window.findChild(QLineEdit, "dbfProductsPathInput").setText(r"C:\legacy\productos.dbf")
    window.findChild(QLineEdit, "dbfEncodingInput").setText("cp850")
    window.findChild(QLineEdit, "dbfSourceSystemInput").setText("sistema_anterior")
    window.findChild(QPushButton, "runLegacyDbfImportButton").click()
    app.processEvents()

    assert calls == [
        (
            {"clients": r"C:\legacy\clientes.dbf", "products": r"C:\legacy\productos.dbf"},
            "sistema_anterior",
            "cp850",
        )
    ]
    from app.ui.form_feedback import FormFeedback

    feedback = window.findChild(FormFeedback, "legacyDbfImportFeedback")
    table = window.findChild(QTableWidget, "legacyDbfImportSummaryTable")
    assert "Importación finalizada" in feedback.text()
    assert table.rowCount() == 5
    assert table.columnCount() == 6
    assert table.horizontalHeaderItem(4).text() == "Advertencias"
    assert table.item(0, 0).text() == "Clientes"
    assert table.item(0, 1).text() == "2"
    assert table.item(2, 4).text() == "1"
    assert "1 advertencia" in feedback.text()
    assert feedback.kind == "warning"
    assert not feedback.isHidden()


def test_legacy_dbf_import_page_exposes_dgr_reference_section(db):
    from PyQt5.QtWidgets import QLineEdit, QPushButton

    app, window = _admin_window("admin_dgr_reference_ui")
    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()

    for object_name in (
        "dgrPaisesPathInput",
        "dgrProvinciasPathInput",
        "dgrLocalidadesPathInput",
        "dgrLocdgrPathInput",
    ):
        assert window.findChild(QLineEdit, object_name) is not None
    assert window.findChild(QPushButton, "runDgrImportButton") is not None


def test_dgr_reference_import_runs_and_shows_summary(db, monkeypatch):
    from PyQt5.QtWidgets import QLineEdit, QPushButton, QTableWidget

    from app.ui import desktop_app
    from app.ui.form_feedback import FormFeedback

    calls = []

    class FakeDgrImporter:
        def import_dbf_files(self, paths_by_entity, *, source_system, encoding):
            calls.append((paths_by_entity, source_system, encoding))
            return {
                "paises": {
                    "created": 2,
                    "updated": 1,
                    "imported": 0,
                    "skipped": 0,
                    "errors": [],
                    "warnings": [],
                },
                "provincias": {
                    "created": 1,
                    "updated": 0,
                    "imported": 0,
                    "skipped": 0,
                    "errors": [],
                    "warnings": [{"code": "province_without_code", "source_id": "-"}],
                },
                "localidades": {
                    "created": 5,
                    "updated": 2,
                    "imported": 0,
                    "skipped": 0,
                    "errors": [],
                    "warnings": [],
                },
            }

    monkeypatch.setattr(desktop_app, "DgrReferenceImporter", FakeDgrImporter)

    app, window = _admin_window("admin_dgr_run_ui")
    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()

    window.findChild(QLineEdit, "dgrPaisesPathInput").setText(r"C:\legacy\paises.dbf")
    window.findChild(QLineEdit, "dgrLocalidadesPathInput").setText(r"C:\legacy\localidades.dbf")
    window.findChild(QLineEdit, "dbfEncodingInput").setText("cp850")
    window.findChild(QPushButton, "runDgrImportButton").click()
    app.processEvents()

    assert calls == [
        (
            {"paises": r"C:\legacy\paises.dbf", "localidades": r"C:\legacy\localidades.dbf"},
            "legacy_dbf",
            "cp850",
        )
    ]
    feedback = window.findChild(FormFeedback, "dgrReferenceFeedback")
    table = window.findChild(QTableWidget, "dgrReferenceSummaryTable")
    assert "Referencia DGR importada" in feedback.text()
    assert table.rowCount() == 3
    assert table.columnCount() == 6
    assert table.item(0, 0).text() == "Países"
    assert table.item(0, 1).text() == "2"
    assert table.item(1, 4).text() == "1"
    assert "1 advertencia" in feedback.text()
    assert feedback.kind == "warning"


def test_dgr_reference_import_requires_at_least_one_file(db):
    from PyQt5.QtWidgets import QPushButton, QTableWidget

    from app.ui.form_feedback import FormFeedback

    app, window = _admin_window("admin_dgr_empty_ui")
    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()

    window.findChild(QPushButton, "runDgrImportButton").click()
    app.processEvents()

    feedback = window.findChild(FormFeedback, "dgrReferenceFeedback")
    table = window.findChild(QTableWidget, "dgrReferenceSummaryTable")
    assert feedback.kind == "warning"
    assert table.rowCount() == 0


def test_legacy_dbf_import_refreshes_master_grids(db, monkeypatch):
    from PyQt5.QtWidgets import QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Carrier, Client
    from app.ui import desktop_app

    class FakeImporter:
        def import_dbf_files(self, paths_by_entity, *, source_system, encoding):
            Client.create(
                name="Cliente Importado UI",
                cuit="30700000123",
                iva_condition="RI",
                source_system=source_system,
                source_id="CLI-1",
            )
            Carrier.create(
                name="Transporte Importado UI",
                cuit="30700000456",
                source_system=source_system,
                source_id="TRA-1",
            )
            return {
                "clients": {"created": 1, "updated": 0, "skipped": 0, "errors": []},
                "carriers": {"created": 1, "updated": 0, "skipped": 0, "errors": []},
                "drivers": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
                "trucks": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
                "products": {"created": 0, "updated": 0, "skipped": 0, "errors": []},
            }

    monkeypatch.setattr(desktop_app, "LegacyDbfMasterImporter", FakeImporter)

    app, window = _admin_window("admin_import_refresh_ui")
    assert window.findChild(QTableWidget, "clientTable").rowCount() == 0
    assert window.findChild(QTableWidget, "newCarrierButtonTable").rowCount() == 0

    window._navigate_to_route("legacy_dbf_import")
    app.processEvents()
    window.findChild(QLineEdit, "dbfClientsPathInput").setText(r"C:\legacy\clientes.dbf")
    window.findChild(QLineEdit, "dbfCarriersPathInput").setText(r"C:\legacy\transportes.dbf")
    window.findChild(QPushButton, "runLegacyDbfImportButton").click()
    app.processEvents()

    client_table = window.findChild(QTableWidget, "clientTable")
    carrier_table = window.findChild(QTableWidget, "newCarrierButtonTable")
    assert client_table.rowCount() == 1
    assert client_table.item(0, 0).text() == "Cliente Importado UI"
    assert carrier_table.rowCount() == 1
    assert carrier_table.item(0, 0).text() == "Transporte Importado UI"

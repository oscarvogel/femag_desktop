import json
from decimal import Decimal


def test_legacy_dbf_master_import_creates_traceable_records(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Carrier, Client, Driver, Product, Truck
    from app.models.system import ImportBatch

    importer = LegacyDbfMasterImporter()
    result = importer.import_rows(
        {
            "clients": [
                {
                    "CODIGO": " C001 ",
                    "RAZON": " Cliente Norte ",
                    "CUIT": "30-71111111-8",
                    "IVA": "Responsable Inscripto",
                    "TELEFONO": "3764",
                    "EMAIL": "ventas@example.com",
                }
            ],
            "carriers": [{"CODIGO": "T001", "NOMBRE": "Transporte Norte", "CUIT": "30-72222222-9"}],
            "drivers": [{"CODIGO": "D001", "NOMBRE": "Juan Perez", "TRANSP": "T001", "DNI": "123"}],
            "trucks": [{"CODIGO": "M001", "PATENTE": " ab 123 cd ", "TRANSP": "T001"}],
            "products": [{"CODIGO": "P001", "NOMBRE": "Fecula de mandioca", "UNIDAD": " kg "}],
        },
        source_system="legacy_dbf",
    )

    assert result["clients"]["created"] == 1
    assert result["carriers"]["created"] == 1
    assert result["drivers"]["created"] == 1
    assert result["trucks"]["created"] == 1
    assert result["products"]["created"] == 1

    client = Client.get()
    carrier = Carrier.get()
    driver = Driver.get()
    truck = Truck.get()
    product = Product.get()
    batch = ImportBatch.get()

    assert client.name == "Cliente Norte"
    assert client.cuit == "30711111118"
    assert client.source_system == "legacy_dbf"
    assert client.source_id == "C001"
    assert client.last_import_batch == batch
    assert carrier.source_id == "T001"
    assert driver.carrier == carrier
    assert truck.domain == "AB123CD"
    assert product.unit == "kg"
    assert product.peso_unitario_kg == Decimal("0.000")
    assert json.loads(batch.summary)["clients"]["created"] == 1


def test_legacy_product_reimport_preserves_manually_entered_weight(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Product

    importer = LegacyDbfMasterImporter()
    rows = {"products": [{"CODIGO": "P001", "NOMBRE": "Fecula", "UNIDAD": "kg"}]}
    importer.import_rows(rows, source_system="legacy_dbf")
    product = Product.get()
    product.peso_unitario_kg = Decimal("25.000")
    product.save()

    importer.import_rows(rows, source_system="legacy_dbf")

    assert Product.get_by_id(product.id).peso_unitario_kg == Decimal("25.000")


def test_legacy_dbf_master_import_is_idempotent_and_source_wins(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Client
    from app.models.system import ImportBatch

    importer = LegacyDbfMasterImporter()
    importer.import_rows(
        {
            "clients": [
                {"CODIGO": "C001", "RAZON": "Cliente Norte", "CUIT": "30711111118", "IVA": "RI", "TELEFONO": "111"}
            ]
        },
        source_system="legacy_dbf",
    )

    result = importer.import_rows(
        {
            "clients": [
                {
                    "CODIGO": "C001",
                    "RAZON": "Cliente Norte Actualizado",
                    "CUIT": "30711111118",
                    "IVA": "RI",
                    "TELEFONO": "222",
                }
            ]
        },
        source_system="legacy_dbf",
    )

    assert result["clients"]["created"] == 0
    assert result["clients"]["updated"] == 1
    assert Client.select().count() == 1
    client = Client.get()
    assert client.name == "Cliente Norte Actualizado"
    assert client.phone == "222"
    assert client.imported_at is not None
    assert client.updated_from_source_at is not None
    assert ImportBatch.select().count() == 2


def test_legacy_dbf_imports_driver_without_carrier_and_preserves_cuit(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver, Truck

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {
                    "CODIGO": "0001",
                    "NOMBRE": "Chofer Legacy",
                    "CUIT": "20-12345678-3",
                    "CHASIS": "ABC123",
                    "ACOPLADO": "DEF456",
                }
            ]
        },
        source_system="legacy_dbf",
    )

    driver = Driver.get()

    assert result["drivers"]["created"] == 1
    assert result["drivers"]["errors"] == []
    assert driver.carrier is None
    assert driver.cuit == "20123456783"
    assert Truck.select().count() == 0


def test_legacy_dbf_driver_with_unknown_explicit_carrier_is_reported(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {
                    "CODIGO": "0002",
                    "NOMBRE": "Chofer con referencia invalida",
                    "CUIT": "20-98765432-1",
                    "TRANSP": "T999",
                }
            ]
        },
        source_system="legacy_dbf",
    )

    assert result["drivers"]["created"] == 0
    assert result["drivers"]["errors"] == [
        {"source_id": "0002", "message": "No existe transportista legacy T999."}
    ]
    assert Driver.select().count() == 0


def test_legacy_dbf_driver_without_carrier_is_idempotent(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    importer = LegacyDbfMasterImporter()
    row = {"CODIGO": "0003", "NOMBRE": "Chofer Repetido", "CUIT": "27-11111111-9"}

    first = importer.import_rows({"drivers": [row]}, source_system="legacy_dbf")
    second = importer.import_rows({"drivers": [row]}, source_system="legacy_dbf")

    assert first["drivers"]["created"] == 1
    assert second["drivers"]["updated"] == 1
    assert Driver.select().count() == 1
    assert Driver.get().carrier is None


def test_legacy_dbf_master_import_adopts_existing_natural_key_with_trace(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Client

    Client.create(name="Cliente preexistente", cuit="30711111118", iva_condition="RI")

    result = LegacyDbfMasterImporter().import_rows(
        {
            "clients": [
                {
                    "CODIGO": "C001",
                    "RAZON": "Cliente desde DBF",
                    "CUIT": "30-71111111-8",
                    "IVA": "RI",
                }
            ]
        },
        source_system="legacy_dbf",
    )

    client = Client.get()
    assert result["clients"]["updated"] == 1
    assert Client.select().count() == 1
    assert client.name == "Cliente desde DBF"
    assert client.source_id == "C001"
    assert client.imported_at is not None


def test_legacy_dbf_master_import_reports_invalid_rows_without_stopping_batch(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Client

    importer = LegacyDbfMasterImporter()
    result = importer.import_rows(
        {
            "clients": [
                {"CODIGO": "", "RAZON": "Sin codigo", "CUIT": "30711111118", "IVA": "RI"},
                {"CODIGO": "C002", "RAZON": "Cliente Sur", "CUIT": "30-73333333-0", "IVA": "RI"},
            ]
        },
        source_system="legacy_dbf",
    )

    assert result["clients"]["created"] == 1
    assert result["clients"]["errors"] == [
        {"source_id": "", "message": "clients requiere CODIGO, RAZON y CUIT."}
    ]
    assert Client.select().count() == 1


def test_legacy_dbf_import_cli_builds_entity_paths():
    from scripts.import_legacy_dbf_masters import build_paths_by_entity

    class Args:
        clients = "clientes.dbf"
        carriers = None
        drivers = "choferes.dbf"
        trucks = None
        products = "productos.dbf"

    assert build_paths_by_entity(Args) == {
        "clients": "clientes.dbf",
        "drivers": "choferes.dbf",
        "products": "productos.dbf",
    }

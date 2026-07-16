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
    truck = Truck.get()
    assert driver.usual_truck == truck
    assert truck.domain == "ABC123"
    assert truck.trailer_domain == "DEF456"
    assert truck.carrier is None


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


def test_legacy_driver_code_requires_compatible_cuit(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "0004", "NOMBRE": "Vogel Ricardo", "CUIT": "20-23737702-9"}
            ],
            "drivers": [
                {"CODIGO": "0004", "NOMBRE": "Bosing Sergio", "CUIT": "20-30717891-6"}
            ],
        },
        source_system="legacy_dbf",
    )

    assert Driver.get().carrier is None
    assert result["drivers"]["warnings"] == [
        {"code": "carrier_code_collision", "source_id": "0004"}
    ]


def test_legacy_driver_uses_unique_carrier_cuit_when_code_collides(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "0009", "NOMBRE": "Mendieta Gabriel", "CUIT": "20-24834384-3"},
                {"CODIGO": "0012", "NOMBRE": "Petrasek Jose", "CUIT": "23-17829761-9"},
            ],
            "drivers": [
                {"CODIGO": "0012", "NOMBRE": "Mendieta Gabriel", "CUIT": "20-24834384-3"}
            ],
        },
        source_system="legacy_dbf",
    )

    assert Driver.get().carrier.source_id == "0009"
    assert result["drivers"]["warnings"] == []


def test_legacy_driver_without_safe_carrier_is_imported_with_warning(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {"CODIGO": "0015", "NOMBRE": "Chofer sin relacion", "CUIT": "20-11111111-1"}
            ]
        },
        source_system="legacy_dbf",
    )

    assert Driver.get().carrier is None
    assert result["drivers"]["created"] == 1
    assert result["drivers"]["warnings"] == [
        {"code": "carrier_not_found", "source_id": "0015"}
    ]


def test_legacy_driver_ambiguous_carrier_cuit_is_not_assigned(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "T1", "NOMBRE": "Transporte Uno", "CUIT": "30-71111111-8"},
                {"CODIGO": "T2", "NOMBRE": "Transporte Dos", "CUIT": "30-71111111-8"},
            ],
            "drivers": [
                {"CODIGO": "D1", "NOMBRE": "Chofer ambiguo", "CUIT": "30-71111111-8"}
            ],
        },
        source_system="legacy_dbf",
    )

    assert Driver.get().carrier is None
    assert result["drivers"]["warnings"] == [
        {"code": "carrier_cuit_ambiguous", "source_id": "D1"}
    ]


def test_legacy_driver_creates_habitual_truck_and_trailer(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver

    result = LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "0001", "NOMBRE": "Aguirre Jorge", "CUIT": "20-26565521-2"}
            ],
            "drivers": [
                {
                    "CODIGO": "0001",
                    "NOMBRE": "Aguirre Jorge",
                    "CUIT": "20-26565521-2",
                    "CHASIS": " ab 123 cd ",
                    "ACOPLADO": " de 456 fg ",
                }
            ],
        },
        source_system="legacy_dbf",
    )

    driver = Driver.get()
    assert driver.usual_truck.domain == "AB123CD"
    assert driver.usual_truck.trailer_domain == "DE456FG"
    assert driver.usual_truck.carrier == driver.carrier
    assert result["trucks"]["created"] == 1


def test_legacy_drivers_reuse_same_normalized_habitual_truck(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver, Truck

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {"CODIGO": "0011", "NOMBRE": "Chofer Uno", "CHASIS": "LAB956", "ACOPLADO": "AB225BM"},
                {"CODIGO": "0014", "NOMBRE": "Chofer Dos", "CHASIS": " lab-956 ", "ACOPLADO": "AB225BM"},
            ]
        },
        source_system="legacy_dbf",
    )

    truck = Truck.get()
    assert Truck.select().count() == 1
    assert Driver.select().where(Driver.usual_truck == truck).count() == 2
    assert result["trucks"]["created"] == 1
    assert result["trucks"]["updated"] == 1


def test_unmatched_legacy_driver_still_creates_unassigned_habitual_truck(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver, Truck

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {
                    "CODIGO": "0015",
                    "NOMBRE": "Chofer sin transporte",
                    "CHASIS": "GWA390",
                    "ACOPLADO": "GWA396",
                }
            ]
        },
        source_system="legacy_dbf",
    )

    driver = Driver.get()
    truck = Truck.get()
    assert driver.carrier is None
    assert truck.carrier is None
    assert driver.usual_truck == truck
    assert result["trucks"]["created"] == 1


def test_legacy_habitual_truck_conflicts_are_reported_without_overwrite(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Carrier, Truck

    existing_carrier = Carrier.create(name="Transportista existente")
    truck = Truck.create(
        domain="CON123",
        trailer_domain="OLD456",
        carrier=existing_carrier,
    )
    result = LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "NUEVO", "NOMBRE": "Transportista nuevo", "CUIT": "30-70000000-1"}
            ],
            "drivers": [
                {
                    "CODIGO": "NUEVO",
                    "NOMBRE": "Transportista nuevo",
                    "CUIT": "30-70000000-1",
                    "CHASIS": "CON123",
                    "ACOPLADO": "NEW789",
                }
            ],
        },
        source_system="legacy_dbf",
    )

    truck = Truck.get_by_id(truck.id)
    warning_codes = {warning["code"] for warning in result["drivers"]["warnings"]}
    assert truck.carrier == existing_carrier
    assert truck.trailer_domain == "OLD456"
    assert warning_codes == {"truck_carrier_conflict", "truck_trailer_conflict"}


def test_legacy_habitual_truck_import_is_idempotent(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Driver, Truck

    importer = LegacyDbfMasterImporter()
    rows = {
        "drivers": [
            {"CODIGO": "0020", "NOMBRE": "Chofer repetido", "CHASIS": "AC141CA", "ACOPLADO": "AC476IH"}
        ]
    }
    first = importer.import_rows(rows, source_system="legacy_dbf")
    second = importer.import_rows(rows, source_system="legacy_dbf")

    assert Driver.select().count() == 1
    assert Truck.select().count() == 1
    assert first["trucks"]["created"] == 1
    assert second["trucks"]["updated"] == 1
    assert second["drivers"]["warnings"] == [
        {"code": "carrier_not_found", "source_id": "0020"}
    ]


def test_legacy_reimport_preserves_manually_completed_driver_relationships(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter
    from app.models.masters import Carrier, Driver, Truck

    importer = LegacyDbfMasterImporter()
    row = {"CODIGO": "0015", "NOMBRE": "Chofer corregido"}
    importer.import_rows({"drivers": [row]}, source_system="legacy_dbf")
    manual_carrier = Carrier.create(name="Transportista corregido")
    manual_truck = Truck.create(domain="MAN123", trailer_domain="MAN456", carrier=manual_carrier)
    driver = Driver.get()
    driver.carrier = manual_carrier
    driver.usual_truck = manual_truck
    driver.save()

    importer.import_rows({"drivers": [row]}, source_system="legacy_dbf")

    driver = Driver.get_by_id(driver.id)
    assert driver.carrier == manual_carrier
    assert driver.usual_truck == manual_truck


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

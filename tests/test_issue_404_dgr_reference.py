from app.config.schema import validate_runtime_schema
from app.importers.dgr_reference import DgrReferenceImporter
from app.models.dgr import DgrCountry, DgrLocality, DgrProvince


ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 1, "DESCRIPCIO": "CAPITAL FEDERAL"}],
    "locdgr": [
        {"IDLOCALIDA": 1, "CODIGODGR": 1, "PROVINCIA": 1, "DPTO": 0,
         "DESCRIPCIO": "CAPITAL FEDERAL"}
    ],
    "localidades": [
        {"CODIGO": "0001", "LOCALIDAD": "CAPITAL FEDERAL", "CODIGODGR": 1,
         "PAISDGR": 200, "PROVDGR": 1, "DEPA": 0, "PROVINCIA": "CAPITAL FEDERAL"}
    ],
}


def test_import_resolves_vfp_codes(db):
    summary = DgrReferenceImporter().import_rows(ROWS)
    assert summary["localidades"]["created"] == 1

    locality = DgrLocality.get(DgrLocality.code == "0001")
    assert locality.name == "CAPITAL FEDERAL"
    assert locality.dgr_code_4 == "0001"
    assert locality.province_code_2 == "01"
    assert locality.department_code_4 == "0000"
    assert locality.country.abbr == "ARG"
    assert locality.country.name == "ARGENTINA"
    assert DgrProvince.get(DgrProvince.code == 1).name == "CAPITAL FEDERAL"


def test_import_is_idempotent(db):
    DgrReferenceImporter().import_rows(ROWS)
    summary = DgrReferenceImporter().import_rows(ROWS)
    assert summary["localidades"]["updated"] == 1
    assert summary["localidades"]["created"] == 0
    assert DgrLocality.select().count() == 1
    assert DgrCountry.select().count() == 1


def test_import_without_dgr_row_warns_and_keeps_locality(db):
    rows = dict(ROWS)
    rows["locdgr"] = []
    summary = DgrReferenceImporter().import_rows(rows)
    codes = [w["code"] for w in summary["localidades"]["warnings"]]
    assert "locality_without_dgr" in codes

    locality = DgrLocality.get(DgrLocality.code == "0001")
    assert locality.dgr_code is None
    assert locality.dgr_code_4 == ""


def test_reference_tables_pass_schema_validation(db):
    DgrReferenceImporter().import_rows(ROWS)
    validate_runtime_schema(db)

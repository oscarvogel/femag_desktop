from app.importers.legacy_dbf_warnings import (
    WARNING_CATALOG,
    classify_warning,
    summarize_import_warnings,
)


def test_warning_catalog_classifies_known_codes():
    assert classify_warning("client_cuit_shared_by_two_rows")["classification"] == "expected"
    assert classify_warning("truck_trailer_conflict")["classification"] == "expected"
    assert classify_warning("carrier_not_found")["classification"] == "review"
    assert classify_warning("carrier_code_collision")["classification"] == "review"
    assert classify_warning("carrier_cuit_ambiguous")["classification"] == "review"
    assert classify_warning("codigo_desconocido")["classification"] == "review"
    assert "client_cuit_shared_by_two_rows" in WARNING_CATALOG


def test_summarize_import_warnings_groups_and_marks_manual_review():
    summary = {
        "clients": {
            "warnings": [
                {"code": "client_cuit_shared_by_two_rows", "source_id": "0100"},
                {"code": "client_cuit_shared_by_two_rows", "source_id": "0101"},
            ],
            "errors": [],
        },
        "drivers": {
            "warnings": [
                {"code": "carrier_not_found", "source_id": "0015"},
                {"code": "truck_trailer_conflict", "source_id": "0015"},
            ],
            "errors": [
                {"source_id": "0090", "message": "drivers requiere CODIGO, RAZON y CUIT."}
            ],
        },
    }

    result = summarize_import_warnings(summary)

    assert result["total_warnings"] == 4
    assert result["total_errors"] == 1
    assert result["by_code"]["client_cuit_shared_by_two_rows"] == 2
    assert result["by_code"]["carrier_not_found"] == 1
    assert result["by_classification"] == {"expected": 3, "review": 1, "bug": 0}
    assert len(result["manual_review"]) == 2
    assert {item["code"] for item in result["manual_review"]} == {"carrier_not_found", "error"}
    assert result["errors"][0]["source_id"] == "0090"


def test_import_summary_includes_classification(db):
    from app.importers.legacy_dbf import LegacyDbfMasterImporter

    result = LegacyDbfMasterImporter().import_rows(
        {
            "drivers": [
                {"CODIGO": "0015", "NOMBRE": "Chofer sin transportista"},
                {"NOMBRE": "Chofer sin codigo"},
            ]
        },
        source_system="legacy_dbf",
    )

    warning_summary = result["warning_summary"]
    assert warning_summary["total_warnings"] == 1
    assert warning_summary["total_errors"] == 1
    assert warning_summary["by_code"]["carrier_not_found"] == 1
    assert warning_summary["by_classification"]["review"] == 1
    assert warning_summary["by_classification"]["expected"] == 0
    review_codes = {item["code"] for item in warning_summary["manual_review"]}
    assert review_codes == {"carrier_not_found", "error"}

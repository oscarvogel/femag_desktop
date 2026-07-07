def test_issue_105_operational_smoke_generates_reproducible_report(tmp_path):
    from scripts.femag_operational_smoke import run_operational_smoke

    database_path = tmp_path / "issue_105_smoke.sqlite3"
    evidence_dir = tmp_path / "issue_105_evidence"
    report_path = tmp_path / "SMOKE_OPERATIVO_FEMAG.md"

    result = run_operational_smoke(
        database_path=database_path,
        evidence_dir=evidence_dir,
        report_path=report_path,
        username="issue105_test",
    )

    assert database_path.exists()
    assert report_path.exists()
    assert result["order_status"] == "Cerrada"
    assert result["driver_released"] is True
    assert result["payment_receipt"].startswith("REC-")
    assert result["balance_after_payment"] == 0.0
    assert result["order_pdf"].exists()
    assert result["order_pdf"].parent == evidence_dir

    report = report_path.read_text(encoding="utf-8")
    assert "# Smoke operativo FEMAG" in report
    assert "No usa datos productivos" in report
    assert "Ordenes de carga" in report
    assert "Cuenta corriente y pagos" in report
    assert "ABMs de transporte" in report
    assert "Remitos" in report
    assert "F150" in report
    assert "Rendicion de transportistas" in report
    assert "Importacion DBF/MySQL" in report
    assert "Modulo no disponible" in report


def test_issue_105_operational_smoke_cli_generates_default_artifacts(tmp_path):
    from scripts.femag_operational_smoke import main

    database_path = tmp_path / "cli_smoke.sqlite3"
    evidence_dir = tmp_path / "cli_evidence"
    report_path = tmp_path / "cli_report.md"

    assert main(
        [
            "--database-path",
            str(database_path),
            "--evidence-dir",
            str(evidence_dir),
            "--report-path",
            str(report_path),
        ]
    ) == 0

    assert database_path.exists()
    assert report_path.exists()
    assert list(evidence_dir.glob("orden_carga_*.pdf"))

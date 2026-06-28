def test_issue_73_integral_demo_runs_full_documental_flow(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from pypdf import PdfReader
    from scripts.issue_73_integral_demo import run_integral_demo

    evidence_dir = tmp_path / "issue_73_evidence"

    first = run_integral_demo(database=db, evidence_dir=evidence_dir, username="issue73_test")
    computer_use_note = "- Computer Use detecto FEMAG Desktop y fallo captura PyQt."
    first["readme"].write_text(
        first["readme"].read_text(encoding="utf-8").replace(
            "Pendiente de registrar en la revision del PR #73. Si falla por PyQt/Windows, no cerrar #69 como validado visualmente.",
            computer_use_note,
        ),
        encoding="utf-8",
    )
    second = run_integral_demo(database=db, evidence_dir=evidence_dir, username="issue73_test")

    assert first["order_number"] != second["order_number"]
    assert first["status"] == "Anulada"
    assert first["destinations"] == 3
    assert first["products"] == 4
    assert first["ledger_originals"] == 2
    assert first["ledger_reversals"] == 2
    assert first["ledger_total"] == 4
    assert first["truck"] == "I730ABC"

    for key in ("order_pdf", "regenerated_pdf", "readme"):
        path = first[key]
        assert path.exists()
        assert path.parent == evidence_dir

    reader = PdfReader(str(first["order_pdf"]))
    order_pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    readme = first["readme"].read_text(encoding="utf-8")

    assert first["order_pdf"] == first["regenerated_pdf"]
    assert "ORDEN DE DESPACHO DE FECULA DE MANDIOCA" in order_pdf_text
    assert "ISSUE73 Cliente Norte" in order_pdf_text
    assert "ISSUE73 Cliente Sur" in order_pdf_text
    assert "I730ABC" in order_pdf_text
    assert "Reimpresion" not in order_pdf_text
    assert "Cuenta corriente documental" in readme
    assert "Camion / patente: I730ABC" in readme
    assert "Orden PDF: `orden_carga_" in readme
    assert "Computer Use" in readme
    assert computer_use_note in readme

    movements = ClientAccountMovement.select().where(ClientAccountMovement.load_order == first["order"])
    assert {movement.source_ref for movement in movements} == {f"LoadOrder:{first['order'].id}"}
    assert {movement.amount for movement in movements} == {0}


def test_issue_73_integral_demo_cli_generates_file_sqlite_database(tmp_path):
    import sqlite3

    from scripts.issue_73_integral_demo import main

    db_path = tmp_path / "femag_demo.sqlite3"
    evidence_dir = tmp_path / "evidence"

    assert main(["--database-path", str(db_path), "--evidence-dir", str(evidence_dir)]) == 0

    assert db_path.exists()
    assert (evidence_dir / "orden_carga_1.pdf").exists()

    connection = sqlite3.connect(db_path)
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "client",
                "clientaddress",
                "carrier",
                "driver",
                "truck",
                "product",
                "loadorder",
                "clientaccountmovement",
            )
        }
    finally:
        connection.close()

    assert counts["client"] >= 2
    assert counts["clientaddress"] >= 3
    assert counts["carrier"] >= 1
    assert counts["driver"] >= 1
    assert counts["truck"] >= 1
    assert counts["product"] >= 3
    assert counts["loadorder"] >= 1
    assert counts["clientaccountmovement"] >= 4

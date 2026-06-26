def test_issue_73_integral_demo_runs_full_documental_flow(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
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

    for key in ("order_html", "summary_html", "reprint_html", "readme"):
        path = first[key]
        assert path.exists()
        assert path.parent == evidence_dir

    order_html = first["order_html"].read_text(encoding="utf-8")
    summary_html = first["summary_html"].read_text(encoding="utf-8")
    reprint_html = first["reprint_html"].read_text(encoding="utf-8")
    readme = first["readme"].read_text(encoding="utf-8")

    assert "Documento logistico interno" in order_html
    assert "Cliente / destino 1" in order_html
    assert "Cliente / destino 2" in order_html
    assert "Cliente / destino 3" in order_html
    assert "Hoja resumen / sobre de carga" in summary_html
    assert "I730ABC" in order_html
    assert "I730ABC" in summary_html
    assert "Reimpresion operativa - Copia para reimpresion" in reprint_html
    assert "Cuenta corriente documental" in readme
    assert "Camion / patente: I730ABC" in readme
    assert "Computer Use" in readme
    assert computer_use_note in readme

    movements = ClientAccountMovement.select().where(ClientAccountMovement.load_order == first["order"])
    assert {movement.source_ref for movement in movements} == {f"LoadOrder:{first['order'].id}"}
    assert {movement.amount for movement in movements} == {0}

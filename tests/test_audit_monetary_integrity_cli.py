"""Salida del auditor de integridad monetaria: resumen, detalle y CSV.

La herramienta es READ-ONLY: estos tests verifican cómo se informa, no que se
repare nada. ``main`` se ejecuta de punta a punta contra una base SQLite
temporal construida en el test.
"""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from peewee import SqliteDatabase

from app.models import ALL_MODELS
from app.services.monetary_audit import (
    BUDGET_HEADER_MISMATCH,
    LEDGER_CANCELLED,
    LEDGER_MATCH_DETAIL,
    LEDGER_MATCH_DETAIL_AND_HEADER,
    LEDGER_MATCH_HEADER,
    LEDGER_MATCH_NEITHER,
    LEDGER_NONE,
    LEDGER_REVERSED,
    ORDER_DRIFT,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    STATUS_OK,
)

DETALLE_000073 = Decimal("37511775.00")
CABECERA_000073 = Decimal("37511800.00")

CSV_COLUMNS = [
    "budget_id",
    "budget_number",
    "client_id",
    "client_name",
    "order_id",
    "order_number",
    "budget_date",
    "budget_status",
    "budget_origin",
    "header_net",
    "header_discount",
    "header_vat",
    "header_total",
    "detail_net",
    "detail_discount",
    "detail_vat",
    "detail_total",
    "diff_net",
    "diff_discount",
    "diff_vat",
    "diff_total",
    "current_order_total",
    "order_budget_difference",
    "ledger_movement_id",
    "ledger_original_total",
    "ledger_detail_difference",
    "ledger_header_difference",
    "budget_integrity",
    "order_budget_status",
    "ledger_integrity",
    "severity",
]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@pytest.fixture()
def populated_db(tmp_path, monkeypatch):
    """Base con el caso 000073 persistido y lista para el CLI."""
    from app.config.database import bind_database
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget, BudgetItem
    from app.models.masters import Client, Product

    path = tmp_path / "cli_audit.sqlite3"
    writable = SqliteDatabase(str(path))
    bind_database(writable)
    writable.connect(reuse_if_open=True)
    writable.create_tables(ALL_MODELS)

    client = Client.create(
        name="CARDOZO MAURICIO GUSTAVO", cuit="30712345678", iva_condition="RI"
    )
    product = Product.create(name="BOLSAS DE FECULA NATIVA", unit="bolsa")

    # Presupuesto manual (sin orden) con cabecera histórica inconsistente.
    presupuesto_73 = Budget.create(
        budget_number=73,
        client=client,
        load_order=None,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=date(2026, 9, 1),
        net_amount=float(CABECERA_000073),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(CABECERA_000073),
    )
    for index, total in enumerate(
        ("48195.00", "31487400.00", "5976180.00"), start=1
    ):
        BudgetItem.create(
            budget=presupuesto_73,
            product=product,
            source_order_product=None,
            quantity=float(index),
            unit="bolsa",
            unit_price=float(total),
            discount_percentage=0.0,
            net_subtotal=float(total),
            discount_amount=0.0,
            net_taxable=float(total),
            vat_percentage=0.0,
            vat_amount=0.0,
            total=float(total),
        )
    ClientAccountMovement.create(
        client=client,
        load_order=None,
        budget=presupuesto_73,
        movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL,
        amount=0.0,
        net_amount=float(CABECERA_000073),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(CABECERA_000073),
        description="Presupuesto PRES-000073 - mercaderia",
        source_ref=f"Budget:{presupuesto_73.id}",
        reference="PRES-000073",
        is_reversal=False,
    )

    # Presupuesto manual consistente, sin movimiento de cuenta corriente.
    presupuesto_74 = Budget.create(
        budget_number=74,
        client=client,
        load_order=None,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=date(2026, 9, 1),
        net_amount=100.0,
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=100.0,
    )
    BudgetItem.create(
        budget=presupuesto_74,
        product=product,
        source_order_product=None,
        quantity=1.0,
        unit="bolsa",
        unit_price=100.0,
        discount_percentage=0.0,
        net_subtotal=100.0,
        discount_amount=0.0,
        net_taxable=100.0,
        vat_percentage=0.0,
        vat_amount=0.0,
        total=100.0,
    )

    writable.close()
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_SQLITE_PATH", str(path))
    yield path
    writable.connect(reuse_if_open=True)
    bind_database(writable)
    writable.drop_tables(ALL_MODELS)
    writable.close()


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------


def _summary_values(salida: str) -> dict[str, str]:
    """Extrae ``label -> valor`` del resumen sin depender del relleno de espacios."""
    from scripts.audit_monetary_integrity import SUMMARY_LABELS

    valores = {}
    for linea in salida.splitlines():
        if ":" not in linea or linea.endswith(":"):
            continue
        etiqueta, _, valor = linea.partition(":")
        etiqueta = etiqueta.strip()
        if etiqueta in SUMMARY_LABELS:
            valores[etiqueta] = valor.strip()
    return valores


def test_resumen_cuenta_cada_clasificacion(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    assert main([]) == 0

    salida = capsys.readouterr().out
    assert "MONETARY INTEGRITY AUDIT" in salida
    valores = _summary_values(salida)
    assert valores["Budgets analyzed"] == "2"
    assert valores["Consistent"] == "1"
    assert valores["Budget header mismatches"] == "1"
    assert valores["Ledger matches detail"] == "0"
    assert valores["Ledger matches header only"] == "1"
    assert valores["Ledger matches neither"] == "0"
    assert valores["Ambiguous ledger"] == "0"
    assert valores["No ledger movement"] == "1"
    assert valores["Critical cases"] == "1"


def test_el_resumen_declara_las_protecciones_read_only(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    main([])

    salida = capsys.readouterr().out
    assert "sql_allowlist_guard" in salida
    assert "sqlite_audit_readonly" in salida


def test_el_resumen_no_suma_diferencias_sin_evidencia_contable(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    main([])

    salida = capsys.readouterr().out
    # Solo el presupuesto 000073 aporta 25 (ledger con cabecera, no con detalle).
    # El presupuesto 74 no aporta nada: no hay evidencia contable.
    assert "Potential financial difference:      $ 25.00" in salida


# ---------------------------------------------------------------------------
# Detalle
# ---------------------------------------------------------------------------


def test_detalle_de_000073_muestra_las_tres_fuentes(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    assert main(["--budget-number", "73"]) == 0

    salida = capsys.readouterr().out
    for seccion in (
        "BUDGET",
        "HEADER",
        "DETAIL",
        "DIFFERENCE",
        "ORDER CURRENT STATE",
        "LEDGER",
        "CLASSIFICATION",
    ):
        assert seccion in salida
    assert "37,511,775.00" in salida  # detalle
    assert "37,511,800.00" in salida  # cabecera y ledger
    assert "CRITICAL" in salida
    assert "BUDGET_HEADER_MISMATCH" in salida
    assert "LEDGER_MATCH_HEADER" in salida
    assert "NO_ORDER" in salida
    assert "No se realizo ninguna modificacion sobre la base." in salida


def test_detalle_por_id_de_presupuesto(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    assert main(["--budget", "1"]) == 0
    assert "PRES-000073" in capsys.readouterr().out


def test_presupuesto_inexistente_no_falla_con_cero_auditados(populated_db, capsys):
    from scripts.audit_monetary_integrity import main

    assert main(["--budget-number", "999"]) == 1
    salida = capsys.readouterr().out
    assert _summary_values(salida)["Budgets analyzed"] == "0"
    assert "No se encontro ningun presupuesto" in salida


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_una_fila_por_presupuesto_con_las_columnas_pedidas(populated_db, tmp_path):
    from scripts.audit_monetary_integrity import main

    destino = tmp_path / "monetary_audit.csv"
    assert main(["--csv", str(destino)]) == 0

    with destino.open(encoding="utf-8", newline="") as handle:
        filas = list(csv.reader(handle))

    assert filas[0] == CSV_COLUMNS
    assert len(filas) == 3

    por_numero = {fila[1]: fila for fila in filas[1:]}
    caso_73 = por_numero["73"]
    assert caso_73[CSV_COLUMNS.index("budget_id")] == "1"
    assert caso_73[CSV_COLUMNS.index("client_name")] == "CARDOZO MAURICIO GUSTAVO"
    assert caso_73[CSV_COLUMNS.index("detail_total")] == "37511775.00"
    assert caso_73[CSV_COLUMNS.index("header_total")] == "37511800.00"
    assert caso_73[CSV_COLUMNS.index("diff_total")] == "25.00"
    assert caso_73[CSV_COLUMNS.index("ledger_original_total")] == "37511800.00"
    assert caso_73[CSV_COLUMNS.index("ledger_detail_difference")] == "25.00"
    assert caso_73[CSV_COLUMNS.index("ledger_header_difference")] == "0.00"
    assert caso_73[CSV_COLUMNS.index("budget_integrity")] == BUDGET_HEADER_MISMATCH
    assert caso_73[CSV_COLUMNS.index("ledger_integrity")] == LEDGER_MATCH_HEADER
    assert caso_73[CSV_COLUMNS.index("severity")] == SEVERITY_CRITICAL
    assert caso_73[CSV_COLUMNS.index("order_budget_status")] == "NO_ORDER"

    caso_74 = por_numero["74"]
    assert caso_74[CSV_COLUMNS.index("diff_total")] == "0.00"
    assert caso_74[CSV_COLUMNS.index("budget_integrity")] == STATUS_OK
    assert caso_74[CSV_COLUMNS.index("ledger_integrity")] == LEDGER_NONE
    assert caso_74[CSV_COLUMNS.index("ledger_movement_id")] == ""
    assert caso_74[CSV_COLUMNS.index("current_order_total")] == ""
    assert caso_74[CSV_COLUMNS.index("severity")] == SEVERITY_INFO


def test_csv_no_trae_datos_de_cliente_sensibles(populated_db, tmp_path):
    from scripts.audit_monetary_integrity import main

    destino = tmp_path / "monetary_audit.csv"
    main(["--csv", str(destino)])

    contenido = destino.read_text(encoding="utf-8")
    assert "30712345678" not in contenido  # CUIT
    assert "mercaderia" not in contenido  # descripcion del movimiento
    assert "Budget:" not in contenido  # source_ref interno


def test_csv_acepta_ruta_relativa(tmp_path, populated_db, monkeypatch):
    from scripts.audit_monetary_integrity import main

    monkeypatch.chdir(tmp_path)
    assert main(["--csv", "monetary_audit.csv"]) == 0

    assert Path(tmp_path / "monetary_audit.csv").exists()

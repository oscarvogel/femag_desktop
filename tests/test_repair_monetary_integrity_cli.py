"""Integración del ENTRYPOINT REAL de la reparación.

El bug anterior escapó a 32 tests unitarios porque todos llamaban
``main([...])`` / ``run_repair([...])`` con una lista explícita. El CLI real,
en cambio, entra por ``python -m scripts.repair_monetary_integrity ...``, que
termina en ``main()`` **sin argumentos**: ahí ``argv`` es ``None`` y argparse
debe leer ``sys.argv[1:]``. Ese camino no estaba cubierto y por eso ambos
identificadores se rechazaban en producción.

Estos tests atacan las dos capas:

* el contrato de parseo con ``argv=None`` reading ``sys.argv`` real;
* el comando real como subproceso, con ``python -m``, que es exactamente lo que
  el operador escribe.

Ninguno toca una base real: la configuración efectiva se aísla apuntando
``LOCALAPPDATA`` a un temporal, que es lo que hace que
``has_runtime_configuration()`` devuelva False, y la base a un SQLite temporal.
"""

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from peewee import SqliteDatabase

from app.models import ALL_MODELS

REPO_ROOT = Path(__file__).resolve().parents[1]

BUDGET_PRES_000099 = 73  # Budget.id = 73 -> PRES-000099
BUDGET_PRES_000073 = 74  # Budget.id = 74 -> PRES-000073

CABECERA = Decimal("37511800.00")
DETALLE = Decimal("37511775.00")


# ---------------------------------------------------------------------------
# Capa 1: contrato de parseo con argv=None (sys.argv real)
# ---------------------------------------------------------------------------


def test_parse_toma_sys_argv_cuando_no_se_pasa_argv(monkeypatch):
    """``argv=None`` debe leerse de ``sys.argv``, no convertirse en lista vacía."""
    from scripts.repair_monetary_integrity import _parse_single_identifier

    monkeypatch.setattr(sys, "argv", ["prog", "--budget", "73"])

    args, identificador = _parse_single_identifier(None)

    assert args.budget == "73"
    assert args.budget_number is None
    assert identificador == 73


def test_parse_toma_sys_argv_para_budget_number(monkeypatch):
    from scripts.repair_monetary_integrity import _parse_single_identifier

    monkeypatch.setattr(sys, "argv", ["prog", "--budget-number", "73"])

    args, identificador = _parse_single_identifier(None)

    assert args.budget is None
    assert args.budget_number == "73"
    assert identificador == 73


def test_main_sin_argv_usa_sys_argv(monkeypatch):
    """``main()`` a secas es lo que invoca el entrypoint del módulo."""
    import scripts.repair_monetary_integrity as modulo

    capturados = {}

    def _fake_run_repair(argv=None):
        capturados["argv"] = argv
        return 0

    monkeypatch.setattr(sys, "argv", ["prog", "--budget", "73"])
    monkeypatch.setattr(modulo, "run_repair", _fake_run_repair)

    assert modulo.main() == 0
    assert capturados["argv"] is None


# ---------------------------------------------------------------------------
# Capa 2: el comando real como subproceso
# ---------------------------------------------------------------------------


def _build_fixture(path: Path) -> None:
    """Crea dos presupuestos reparables con id y número visibles cruzados.

    ``Budget.id=73`` es ``PRES-000099`` y ``Budget.id=74`` es ``PRES-000073``.
    Así, ver cuál se resuelve prueba inequívocamente si el flag seHonró como
    ``budget_id`` o como ``budget_number``.
    """
    from app.config.database import bind_database
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.money import compute_line_amounts

    writable = SqliteDatabase(str(path))
    bind_database(writable)
    writable.connect()
    writable.create_tables(ALL_MODELS)

    carrier = Carrier.create(name="T", cuit="30777777770")
    driver = Driver.create(name="C", carrier=carrier, document="1")
    truck = Truck.create(domain="CLI1", carrier=carrier)
    client = Client.create(name="CLI TEST", cuit="30711111111", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="M",
        city="P",
        address="Ruta 12",
        is_primary=True,
    )
    product = Product.create(name="Fecula", unit="bolsa")
    lineas = (
        ("A", "5", "9639.00"),
        ("B", "840", "37485.00"),
        ("C", "310", "19278.00"),
    )

    for budget_id, budget_number, order_number, movement_id in (
        (BUDGET_PRES_000099, 99, 51, 441),
        (BUDGET_PRES_000073, 73, 52, 442),
    ):
        order = LoadOrder.create(
            order_number=order_number,
            client=client,
            delivery_address=address,
            carrier=carrier,
            driver=driver,
            truck=truck,
        )
        destination = LoadOrderDestination.create(
            order=order, client=client, delivery_address=address, sequence=1
        )
        rows = []
        for name, quantity, price in lineas:
            amounts = compute_line_amounts(
                quantity=quantity,
                unit_price=price,
                discount_percentage="0",
                vat_percentage="0",
            )
            rows.append(
                LoadOrderProduct.create(
                    order=order,
                    destination=destination,
                    product=product,
                    quantity=float(amounts.quantity),
                    unit="bolsa",
                    precio_neto_unitario=float(amounts.unit_price),
                    descuento_porcentaje=0.0,
                    neto_subtotal=float(amounts.net_subtotal),
                    descuento_importe=float(amounts.discount_amount),
                    neto_gravado=float(amounts.net_taxable),
                    iva_porcentaje=0.0,
                    iva_importe=float(amounts.vat_amount),
                    total=float(amounts.total),
                )
            )
        budget = Budget.create(
            id=budget_id,
            budget_number=budget_number,
            client=client,
            load_order=order,
            origin=Budget.ORIGIN_LOAD_ORDER,
            issue_date=order.date,
            net_amount=float(CABECERA),
            discount_amount=0.0,
            vat_amount=0.0,
            total_amount=float(CABECERA),
        )
        for row in rows:
            BudgetItem.create(
                budget=budget,
                product=row.product,
                source_order_product=row,
                quantity=row.quantity,
                unit=row.unit,
                unit_price=row.precio_neto_unitario,
                discount_percentage=0.0,
                net_subtotal=row.neto_subtotal,
                discount_amount=row.descuento_importe,
                net_taxable=row.neto_gravado,
                vat_percentage=row.iva_porcentaje,
                vat_amount=row.iva_importe,
                total=row.total,
            )
        ClientAccountMovement.create(
            id=movement_id,
            client=client,
            load_order=order,
            budget=budget,
            movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
            amount=0.0,
            net_amount=float(CABECERA),
            discount_amount=0.0,
            vat_amount=0.0,
            total_amount=float(CABECERA),
            movement_date=order.date,
            due_date=order.date,
            description=f"Presupuesto PRES-{budget_number:06d}",
            source_ref=f"Budget:{budget.id}",
            reference=f"PRES-{budget_number:06d}",
            is_reversal=False,
        )

    writable.close()


@pytest.fixture()
def cli(tmp_path):
    """Ejecuta el comando real como subproceso, sobre una base temporal."""
    base = tmp_path / "cli.sqlite3"
    _build_fixture(base)
    local_app_data = tmp_path / "localappdata"
    local_app_data.mkdir()

    def _run(*args, timeout=180):
        env = dict(os.environ)
        env.update(
            {
                # Sin configuración segura en este "puesto": la configuración
                # efectiva viene del entorno.
                "LOCALAPPDATA": str(local_app_data),
                "FEMAG_ENV_FILE": str(tmp_path / "missing.env"),
                "FEMAG_DB_ENGINE": "sqlite",
                "FEMAG_SQLITE_PATH": str(base),
                "FEMAG_DEMO": "0",
                "FEMAG_SECURE_CONFIG": "0",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        proceso = subprocess.run(
            [sys.executable, "-m", "scripts.repair_monetary_integrity", *args],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return proceso

    return _run, base


def test_cli_real_budget_llega_al_plan_del_presupuesto_por_id(cli):
    """--budget 73 resuelve Budget.id=73, que en esta base es PRES-000099."""
    run, base = cli
    antes = base.read_bytes()

    proceso = run("--budget", "73")

    salida = proceso.stdout + proceso.stderr
    assert proceso.returncode == 0, salida
    assert "REPAIR PLAN" in salida
    assert "PRES-000099" in salida
    assert f"id:            {BUDGET_PRES_000099}" in salida
    assert "PRES-000073" not in salida
    assert "No se encontró el presupuesto" not in salida
    assert "ABORTED" not in salida
    assert base.read_bytes() == antes, "El dry-run no debe tocar la base"


def test_cli_real_budget_number_llega_al_plan_por_numero_visible(cli):
    """--budget-number 73 resuelve Budget.budget_number=73, que es PRES-000073."""
    run, base = cli
    antes = base.read_bytes()

    proceso = run("--budget-number", "73")

    salida = proceso.stdout + proceso.stderr
    assert proceso.returncode == 0, salida
    assert "REPAIR PLAN" in salida
    assert "PRES-000073" in salida
    assert f"id:            {BUDGET_PRES_000073}" in salida
    assert "PRES-000099" not in salida
    assert "ABORTED" not in salida
    assert base.read_bytes() == antes


def test_cli_real_muestra_los_importes_del_caso_confirmado(cli):
    import re

    run, _base = cli

    proceso = run("--budget", "73")

    salida = proceso.stdout
    plan = re.findall(
        r"(\w+):\s+BEFORE\s+([-\d,.]+)\s+->\s+AFTER\s+([-\d,.]+)\s+DIFF\s+([-\d,.]+)",
        salida,
    )
    assert len(plan) == 8, salida  # 4 del presupuesto + 4 del movimiento
    for nombre, antes, despues, diff in plan:
        if nombre in {"net", "total"}:
            assert (antes, despues, diff) == ("37,511,800.00", "37,511,775.00", "-25.00")
        else:
            assert (antes, despues, diff) == ("0.00", "0.00", "0.00")

    assert re.search(r"id:\s+441", salida)
    assert "load_order_documental" in salida
    assert "source_ref:    Budget:73" in salida
    assert "DRY-RUN: no se modificó nada." in salida
    assert "--apply" in salida


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(("--all",), id="all"),
        pytest.param((), id="sin_identificador"),
        pytest.param(("--budget", "73", "--budget-number", "73"), id="ambos"),
        pytest.param(("--budget", "0"), id="budget_cero"),
        pytest.param(("--budget", "-5"), id="budget_negativo"),
        pytest.param(("--budget", "texto"), id="budget_texto"),
        pytest.param(("--budget", "1.5"), id="budget_decimal"),
        pytest.param(("--budget-number", "0"), id="number_cero"),
        pytest.param(("--budget-number", "-5"), id="number_negativo"),
        pytest.param(("--budget-number", "texto"), id="number_texto"),
        pytest.param(("--budget-number", "*"), id="number_comodin"),
        pytest.param(("--apply",), id="solo_apply"),
    ],
)
def test_cli_real_aborta_sin_identificador_valido(cli, args):
    run, base = cli
    antes = base.read_bytes()

    proceso = run(*args)

    salida = proceso.stdout + proceso.stderr
    assert proceso.returncode == 3, salida
    assert "ABORTED" in salida
    assert "REPAIR PLAN" not in salida
    assert base.read_bytes() == antes


def test_cli_real_dry_run_no_escribe_audit_log(cli):
    """Un dry-run real no deja rastro de auditoría en la base."""
    from app.config.database import bind_database

    run, base = cli

    proceso = run("--budget-number", "73")
    assert proceso.returncode == 0

    from app.models.audit import AuditLog

    control = SqliteDatabase(str(base))
    bind_database(control)
    control.connect()
    try:
        assert AuditLog.select().count() == 0
    finally:
        control.close()

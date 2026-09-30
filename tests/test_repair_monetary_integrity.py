"""Reparación controlada de la inconsistencia monetaria histórica.

La reparación es una herramienta **explícita y de a uno**: recibe UN
identificador de presupuesto, reusa la clasificación del auditor READ-ONLY,
verifica cuatro condiciones y recién entonces escribe. Nunca repara en lote,
nunca adivina y nunca repara una deriva de orden.

Casos probados (1 a 17 del encargo):

1. dry-run no modifica nada            10. fallo al auditar => rollback
2. apply corrige Budget                11. postcondition mala => rollback
3. apply corrige sólo el original      12. cero originales => abort
4. no modifica BudgetItem              13. varios originales => abort
5. no modifica LoadOrderProduct        14. orden != detalle => abort
6. no modifica pagos                   15. presupuesto consistente => no-op
7. no modifica ajustes                 16. segunda ejecución => idempotente
8. crea AuditLog                       17. caso exacto 000073
9. reparación y auditoría son atómicas

Ninguno de estos tests usa la base real: todo corre contra SQLite temporal.
"""

from decimal import Decimal

import pytest
from peewee import SqliteDatabase

from app.models import ALL_MODELS
from app.services.monetary_audit import (
    BUDGET_HEADER_MISMATCH,
    LEDGER_MATCH_DETAIL,
    LEDGER_MATCH_DETAIL_AND_HEADER,
    ORDER_DRIFT,
    STATUS_OK,
)
from scripts.repair_monetary_integrity import (
    ACTION_REPAIR,
    ALREADY_CONSISTENT,
    ALREADY_CONSISTENT_MESSAGE,
    REASON_REPAIR,
    REFUSED,
    REPAIRABLE,
    RepairAborted,
    apply_plan,
    build_plan,
    classify_repair,
    render_plan,
    verify_postconditions,
)

DETALLE = Decimal("37511775.00")
CABECERA = Decimal("37511800.00")
DIFERENCIA = Decimal("-25.00")

CASO_000073 = (
    ("PACK 10 UNID. ALM. MAIZ X 1/2 KG", "5", "9639.00"),
    ("BOLSAS DE FECULA NATIVA", "840", "37485.00"),
    ("PACK 10 UNID. FECULA X 1 KG", "310", "19278.00"),
)

MOVEMENT_ID_000073 = 441


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Base SQLite escribible en archivo, con la configuración efectiva del CLI."""
    from app.config import secure_credentials
    from app.config.database import bind_database
    from app.models.audit import AuditLog

    monkeypatch.setattr(
        secure_credentials, "has_runtime_configuration", lambda config_dir=None: False
    )
    monkeypatch.setenv("FEMAG_DEMO", "0")
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "0")
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    path = tmp_path / "repair.sqlite3"
    monkeypatch.setenv("FEMAG_SQLITE_PATH", str(path))
    writable = SqliteDatabase(str(path))
    bind_database(writable)
    writable.connect(reuse_if_open=True)
    writable.create_tables(ALL_MODELS)
    yield writable
    bind_database(writable)
    writable.drop_tables(ALL_MODELS)
    writable.close()


def _masters():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck

    carrier = Carrier.create(name="Transportista", cuit="30777777770")
    driver = Driver.create(name="Chofer", carrier=carrier, document="1")
    truck = Truck.create(domain="AUD01", carrier=carrier)
    client = Client.create(
        name="CARDOZO MAURICIO GUSTAVO", cuit="30712345678", iva_condition="RI"
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "client": client,
        "address": address,
        "product": Product.create(name="Fecula", unit="bolsa"),
    }


def _caso_000073(*, header_total=CABECERA, movement_total=CABECERA, budget_number=73):
    """Reproduce PRES-000073 con los identificadores reales de producción.

    ``Budget.id = 73`` y ``ClientAccountMovement.id = 441`` se fijan a propósito
    para que los tests hablen de las mismas filas que el reporte del auditor.
    """
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.services.money import compute_line_amounts

    masters = _masters()
    order = LoadOrder.create(
        order_number=51,
        client=masters["client"],
        delivery_address=masters["address"],
        carrier=masters["carrier"],
        driver=masters["driver"],
        truck=masters["truck"],
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=masters["client"],
        delivery_address=masters["address"],
        sequence=1,
    )
    rows = []
    for name, quantity, price in CASO_000073:
        product = masters["product"]
        amounts = compute_line_amounts(
            quantity=quantity, unit_price=price, discount_percentage="0", vat_percentage="0"
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
        id=73,
        budget_number=budget_number,
        client=masters["client"],
        load_order=order,
        origin=Budget.ORIGIN_LOAD_ORDER,
        issue_date=order.date,
        net_amount=float(header_total),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(header_total),
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
        id=MOVEMENT_ID_000073,
        client=masters["client"],
        load_order=order,
        budget=budget,
        payment=None,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=0.0,
        net_amount=float(movement_total),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(movement_total),
        currency="ARS",
        movement_date=order.date,
        due_date=order.date,
        description=f"Presupuesto PRES-{budget_number:06d} / OC-000051",
        source_ref=f"Budget:{budget.id}",
        reference=f"PRES-{budget_number:06d}",
        is_reversal=False,
        created_by="seed",
    )
    return masters, order, budget


def _audit(budget_number=73):
    from scripts.repair_monetary_integrity import audit_budget

    return audit_budget(budget_number=budget_number)


def _snapshot():
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder, LoadOrderProduct

    state = {}
    for model in (Budget, BudgetItem, LoadOrder, LoadOrderProduct, ClientAccountMovement, AuditLog):
        state[model.__name__] = [
            {k: str(v) for k, v in sorted(row.__data__.items())}
            for row in model.select().order_by(model.id)
        ]
    return state


# ---------------------------------------------------------------------------
# 1) DRY-RUN NO MODIFICA NADA
# ---------------------------------------------------------------------------


def test_1_dry_run_no_modifica_absolutamente_nada(db):
    _caso_000073()
    antes = _snapshot()

    from scripts.repair_monetary_integrity import run_repair

    assert run_repair(["--budget-number", "73"]) == 0

    assert _snapshot() == antes


def test_1b_sin_apply_no_hay_audit_log(db):
    from app.models.audit import AuditLog

    _caso_000073()
    run_dry()

    assert AuditLog.select().count() == 0


def run_dry():
    from scripts.repair_monetary_integrity import run_repair

    return run_repair(["--budget-number", "73"])


# ---------------------------------------------------------------------------
# 2, 3, 17) APPLY CORRIGE Budget Y EL MOVIMIENTO ORIGINAL
# ---------------------------------------------------------------------------


def test_17_caso_exacto_000073(db):
    """37.511.800 -> 37.511.775 en cabecera y en el movimiento 441."""
    _masters_moved, _order, budget = _caso_000073()

    assert classify_repair(_audit()).status == REPAIRABLE

    plan = build_plan(_audit())

    assert plan.budget_id == budget.id
    assert plan.movement_id == MOVEMENT_ID_000073
    assert plan.movement_source_ref == f"Budget:{budget.id}"
    assert plan.movement_type == "load_order_documental"
    assert plan.before_budget.total == CABECERA
    assert plan.after_budget.total == DETALLE
    assert plan.before_movement.total == CABECERA
    assert plan.after_movement.total == DETALLE
    assert plan.budget_difference.total == DIFERENCIA
    assert plan.movement_difference.total == DIFERENCIA

    apply_plan(plan, user="admin")

    from app.models.budgets import Budget
    from app.models.accounting import ClientAccountMovement

    corregido = Budget.get_by_id(budget.id)
    assert Decimal(str(corregido.net_amount)) == DETALLE
    assert Decimal(str(corregido.total_amount)) == DETALLE
    movimiento = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
    assert Decimal(str(movimiento.net_amount)) == DETALLE
    assert Decimal(str(movimiento.total_amount)) == DETALLE


def test_2_apply_corrige_budget(db):
    from app.models.budgets import Budget

    _masters_ignored, _order, budget = _caso_000073()

    apply_plan(build_plan(_audit()), user="admin")

    corregido = Budget.get_by_id(budget.id)
    assert Decimal(str(corregido.net_amount)) == DETALLE
    assert Decimal(str(corregido.total_amount)) == DETALLE


def test_3_apply_corrige_exclusivamente_el_movimiento_original(db):
    from app.models.accounting import ClientAccountMovement

    _caso_000073()

    apply_plan(build_plan(_audit()), user="admin")

    movimentos = list(ClientAccountMovement.select())
    assert len(movimentos) == 1
    assert movimentos[0].id == MOVEMENT_ID_000073
    assert Decimal(str(movimentos[0].total_amount)) == DETALLE


def test_3b_no_se_toca_el_importe_documental_amount(db):
    """``amount`` guarda 0 (documental) y no es un campo de importe."""
    from app.models.accounting import ClientAccountMovement

    _caso_000073()
    apply_plan(build_plan(_audit()), user="admin")

    movimiento = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
    assert movimiento.amount == 0.0


# ---------------------------------------------------------------------------
# 4, 5, 6, 7) LO QUE NO SE TOCA
# ---------------------------------------------------------------------------


def test_4_no_modifica_budgetitem(db):
    _caso_000073()
    antes = _snapshot()["BudgetItem"]

    apply_plan(build_plan(_audit()), user="admin")

    assert _snapshot()["BudgetItem"] == antes


def test_5_no_modifica_loadorderproduct(db):
    from app.models.load_orders import LoadOrderProduct

    _caso_000073()
    antes = _snapshot()["LoadOrderProduct"]

    apply_plan(build_plan(_audit()), user="admin")

    assert _snapshot()["LoadOrderProduct"] == antes


def test_6_no_modifica_pagos(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.models.payments import ClientPayment
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073()
    cliente = Client.get(Client.name == "CARDOZO MAURICIO GUSTAVO")
    pago = ClientPayment.create(
        receipt_number="REC-00000001",
        client=cliente,
        payment_date="2026-09-01",
        amount=1000.0,
        method=ClientPayment.METHOD_CASH,
    )
    movimiento_pago = ClientAccountMovement.create(
        client=cliente,
        load_order=None,
        payment=pago,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        amount=-1000.0,
        net_amount=-1000.0,
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=-1000.0,
        description="Pago",
        source_ref=f"ClientPayment:{pago.id}",
        is_reversal=False,
    )

    run_repair(["--budget-number", "73", "--apply"])

    recargado = ClientAccountMovement.get_by_id(movimiento_pago.id)
    assert Decimal(str(recargado.total_amount)) == Decimal("-1000.00")
    assert Decimal(str(recargado.net_amount)) == Decimal("-1000.00")


def test_7_no_modifica_ajustes(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073()
    cliente = Client.get(Client.name == "CARDOZO MAURICIO GUSTAVO")
    ajuste = ClientAccountMovement.create(
        client=cliente,
        load_order=None,
        movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT,
        amount=-500.0,
        net_amount=-500.0,
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=-500.0,
        description="Ajuste manual",
        source_ref="ManualCredit:1",
        is_reversal=False,
    )

    run_repair(["--budget-number", "73", "--apply"])

    recargado = ClientAccountMovement.get_by_id(ajuste.id)
    assert Decimal(str(recargado.total_amount)) == Decimal("-500.00")


# ---------------------------------------------------------------------------
# 8, 9, 10) AUDITORÍA
# ---------------------------------------------------------------------------


def test_8_crea_audit_log(db):
    from app.models.audit import AuditLog

    _caso_000073()

    apply_plan(build_plan(_audit()), user="admin")

    registros = list(AuditLog.select())
    assert len(registros) == 1
    registro = registros[0]
    assert registro.action == ACTION_REPAIR
    assert registro.record_ref == "Budget:73"
    assert registro.observation == REASON_REPAIR
    assert registro.user == "admin"
    nuevo = registro.new_value
    assert nuevo["budget_id"] == 73
    assert nuevo["movement_id"] == MOVEMENT_ID_000073
    assert nuevo["order_number"] == 51
    assert nuevo["client_id"] is not None
    assert nuevo["budget_number"] == 73
    assert nuevo["difference"] == -25.0
    assert nuevo["before_budget"]["total"] == float(CABECERA)
    assert nuevo["after_budget"]["total"] == float(DETALLE)
    assert nuevo["before_ledger"]["total"] == float(CABECERA)
    assert nuevo["after_ledger"]["total"] == float(DETALLE)


def test_8b_el_audit_log_no_guarda_credenciales(db):
    from app.models.audit import AuditLog

    _caso_000073()
    apply_plan(build_plan(_audit()), user="admin")

    crudo = AuditLog.select().first().new_value
    for clave in ("password", "clave", "secret", "host", "user"):
        assert clave not in str(crudo).lower()


def test_9_reparacion_y_auditoria_se_confirman_juntas(db):
    """El registro de auditoría existe si y sólo si los datos se escribieron."""
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.budgets import Budget

    _caso_000073()

    apply_plan(build_plan(_audit()), user="admin")

    reparado = Decimal(str(Budget.get_by_id(73).total_amount)) == DETALLE
    auditado = AuditLog.select().count() == 1
    movimiento_ok = (
        Decimal(str(ClientAccountMovement.get_by_id(MOVEMENT_ID_000073).total_amount))
        == DETALLE
    )
    assert reparado and auditado and movimiento_ok


def test_10_fallo_al_auditar_hace_rollback_completo(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.budgets import Budget

    _caso_000073()
    antes = _snapshot()
    plan = build_plan(_audit())

    import app.services.audit_service as audit_service_module

    def _reventar(self, **kwargs):
        raise RuntimeError("disco de auditoría lleno")

    original = audit_service_module.AuditService.record
    audit_service_module.AuditService.record = _reventar
    try:
        with pytest.raises(RuntimeError):
            apply_plan(plan, user="admin")
    finally:
        audit_service_module.AuditService.record = original

    assert Decimal(str(Budget.get_by_id(73).total_amount)) == CABECERA
    assert Decimal(str(ClientAccountMovement.get_by_id(MOVEMENT_ID_000073).total_amount)) == CABECERA
    assert AuditLog.select().count() == 0
    assert _snapshot() == antes


# ---------------------------------------------------------------------------
# 11) POSTCONDITION
# ---------------------------------------------------------------------------


def test_11_postcondition_incorrecta_hace_rollback(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.budgets import Budget

    _caso_000073()
    antes = _snapshot()
    plan = build_plan(_audit())

    import scripts.repair_monetary_integrity as modulo

    original = modulo.verify_postconditions
    modulo.verify_postconditions = lambda budget_id, movement_id: ["net: forzado"]
    try:
        with pytest.raises(modulo.RepairAborted):
            apply_plan(plan, user="admin")
    finally:
        modulo.verify_postconditions = original

    assert Decimal(str(Budget.get_by_id(73).total_amount)) == CABECERA
    assert AuditLog.select().count() == 0
    assert _snapshot() == antes


def test_11b_postcondition_real_pasa_tras_la_reparacion(db):
    _caso_000073()
    apply_plan(build_plan(_audit()), user="admin")

    assert verify_postconditions(73, MOVEMENT_ID_000073) == []


def test_11c_postcondition_falla_si_el_detalle_no_cierra(db):
    from app.models.budgets import Budget

    _caso_000073()

    Budget.update(total_amount=float(DETALLE + 1)).where(Budget.id == 73).execute()

    violations = verify_postconditions(73, MOVEMENT_ID_000073)

    assert any("total" in v for v in violations)


# ---------------------------------------------------------------------------
# 12, 13, 14) ABORTES
# ---------------------------------------------------------------------------


def test_12_cero_movimientos_originales_aborta(db):
    from app.models.accounting import ClientAccountMovement

    _caso_000073()
    ClientAccountMovement.delete().where(
        ClientAccountMovement.id == MOVEMENT_ID_000073
    ).execute()

    audit = _audit()

    assert classify_repair(audit).status == REFUSED
    with pytest.raises(RepairAborted):
        build_plan(audit)


def test_13_multiples_movimientos_originales_aborta(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client

    _caso_000073()
    cliente = Client.get(Client.name == "CARDOZO MAURICIO GUSTAVO")
    ClientAccountMovement.create(
        client=cliente,
        load_order=None,
        budget=None,
        movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL,
        amount=0.0,
        net_amount=float(CABECERA),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(CABECERA),
        description="Segundo original",
        source_ref=f"LoadOrder:{MOVEMENT_ID_000073}",
        reference="PRES-000073",
        is_reversal=False,
    )

    audit = _audit()

    assert classify_repair(audit).status == REFUSED
    with pytest.raises(RepairAborted):
        build_plan(audit)


def test_14_orden_distinta_al_detalle_aborta(db):
    from app.models.load_orders import LoadOrderProduct

    _caso_000073()
    fila = LoadOrderProduct.get_by_id(1)
    fila.precio_neto_unitario = 20000.0
    fila.neto_subtotal = 100000.0
    fila.neto_gravado = 100000.0
    fila.total = 100000.0
    fila.save()

    audit = _audit()

    assert audit.order_budget == ORDER_DRIFT
    assert classify_repair(audit).status == REFUSED
    with pytest.raises(RepairAborted):
        build_plan(audit)


def test_14b_drift_sin_mismatch_de_cabecera_no_se_toca(db):
    """El encargo pide no tocar ORDER_BUDGET_DRIFT: el ledger coincide."""
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget
    from app.models.load_orders import LoadOrderProduct

    _caso_000073()
    # Cabecera coherente con el detalle, pero la orden cambió después.
    Budget.update(net_amount=float(DETALLE), total_amount=float(DETALLE)).where(
        Budget.id == 73
    ).execute()
    ClientAccountMovement.update(
        net_amount=float(DETALLE), total_amount=float(DETALLE)
    ).where(ClientAccountMovement.id == MOVEMENT_ID_000073).execute()
    fila = LoadOrderProduct.get_by_id(1)
    fila.precio_neto_unitario = 20000.0
    fila.neto_subtotal = 100000.0
    fila.neto_gravado = 100000.0
    fila.total = 100000.0
    fila.save()

    audit = _audit()

    assert audit.budget_integrity == STATUS_OK
    assert audit.order_budget == ORDER_DRIFT
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert classify_repair(audit).status == ALREADY_CONSISTENT


def test_14c_ledger_que_no_coincide_con_la_cabecera_aborta(db):
    from app.models.accounting import ClientAccountMovement

    _caso_000073()
    ClientAccountMovement.update(total_amount=99999.0).where(
        ClientAccountMovement.id == MOVEMENT_ID_000073
    ).execute()

    audit = _audit()

    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert classify_repair(audit).status == REFUSED


# ---------------------------------------------------------------------------
# 15, 16) NO-OP E IDEMPOTENCIA
# ---------------------------------------------------------------------------


def test_15_presupuesto_consistente_no_hace_nada(db):
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073(header_total=DETALLE, movement_total=DETALLE)
    antes = _snapshot()

    assert classify_repair(_audit()).status == ALREADY_CONSISTENT
    assert run_repair(["--budget-number", "73"]) == 0

    assert _snapshot() == antes


def test_15b_presupuesto_consistente_informa_ya_consistente(db, capsys):
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073(header_total=DETALLE, movement_total=DETALLE)

    run_repair(["--budget-number", "73", "--apply"])

    assert ALREADY_CONSISTENT_MESSAGE in capsys.readouterr().out


def test_16_segunda_ejecucion_es_idempotente(db):
    from app.models.audit import AuditLog
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073()

    assert run_repair(["--budget-number", "73", "--apply"]) == 0
    despues_de_primera = _snapshot()
    assert AuditLog.select().count() == 1

    assert run_repair(["--budget-number", "73", "--apply"]) == 0

    assert AuditLog.select().count() == 1, "No debe crear un AuditLog duplicado"
    assert _snapshot() == despues_de_primera


def test_16b_despues_de_la_reparacion_el_auditor_da_cero(db):
    from scripts.repair_monetary_integrity import run_repair

    _caso_000073()
    run_repair(["--budget-number", "73", "--apply"])

    audit = _audit()

    assert audit.budget_integrity == STATUS_OK
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.potential_financial_difference == Decimal("0.00")


# ---------------------------------------------------------------------------
# SEGURIDAD DE LA INTERFAZ
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--all"],
        ["--budget", "73", "--budget-number", "73"],
        [],
        ["--budget-number", "*"],
    ],
)
def test_no_permite_reparacion_en_lote_ni_sin_identificador(db, argv, capsys):
    from scripts.repair_monetary_integrity import run_repair

    with pytest.raises(RepairAborted):
        run_repair(argv)


def test_plan_mostrado_en_dry_run(db, capsys):
    import re

    from scripts.repair_monetary_integrity import run_repair

    _caso_000073()

    run_repair(["--budget-number", "73"])

    salida = capsys.readouterr().out
    assert "REPAIR PLAN" in salida
    assert "DRY-RUN" in salida
    # Cabecera y movimiento: 37.511.800 -> 37.511.775, diferencia -25.00
    lineas = re.findall(r"(\w+):\s+BEFORE\s+([-\d,.]+)\s+->\s+AFTER\s+([-\d,.]+)\s+DIFF\s+([-\d,.]+)", salida)
    assert lineas, salida
    for nombre, antes, despues, diff in lineas:
        if nombre in {"net", "total"}:
            assert (antes, despues, diff) == ("37,511,800.00", "37,511,775.00", "-25.00")
        else:
            assert (antes, despues, diff) == ("0.00", "0.00", "0.00")
    assert len(lineas) == 8  # 4 del presupuesto + 4 del movimiento
    assert re.search(r"id:\s+441", salida)
    assert "Budget:73" in salida
    assert "load_order_documental" in salida


def test_render_plan_no_pide_apply_por_si_mismo(db):
    _caso_000073()

    texto = render_plan(build_plan(_audit()))

    assert "REPAIR PLAN" in texto
    assert "PRES-000073" in texto
    assert "OC-000051" in texto

"""Garantía READ-ONLY y lectura real del auditor de integridad monetaria.

Dos objetivos de estos tests:

1. **Defensa técnica**: la conexión que usa el auditor no puede escribir, ni
   siquiera por accidente. Se verifica que el guard de SQL rechaza verbos de
   escritura y que el motor SQLite abre el archivo en modo solo lectura.
2. **No mutación**: construir la base, ejecutar el auditor completo y comprobar
   que ninguna tabla cambió. Se comparan cantidad de filas y hash de contenido
   de ``Budget``, ``BudgetItem``, ``LoadOrder``, ``LoadOrderProduct``,
   ``ClientAccountMovement`` y ``AuditLog``.

Nada de lo que se prueba aquí repara, migra ni regenera importes.
"""

import json
import sqlite3
from decimal import Decimal
from hashlib import sha256

import pytest
from peewee import SqliteDatabase

from app.models import ALL_MODELS
from app.services.monetary_audit import (
    LEDGER_AMBIGUOUS,
    LEDGER_MATCH_DETAIL,
    LEDGER_MATCH_DETAIL_AND_HEADER,
    LEDGER_MATCH_HEADER,
    LEDGER_MATCH_NEITHER,
    LEDGER_NONE,
    LEDGER_REVERSED,
    ORDER_DRIFT,
    ORDER_MATCH,
    ORDER_NO_ORDER,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_OK,
    BUDGET_HEADER_MISMATCH,
)

SNAPSHOT_TABLES = (
    "Budget",
    "BudgetItem",
    "LoadOrder",
    "LoadOrderProduct",
    "ClientAccountMovement",
    "AuditLog",
)

DETALLE_000073 = Decimal("37511775.00")
CABECERA_000073 = Decimal("37511800.00")

CASO_000073 = (
    ("PACK 10 UNID. ALM. MAIZ X 1/2 KG", "5", "9639.00"),
    ("BOLSAS DE FECULA NATIVA", "840", "37485.00"),
    ("PACK 10 UNID. FECULA X 1 KG", "310", "19278.00"),
)


# ---------------------------------------------------------------------------
# Fixture: base real en archivo + handle READ-ONLY sobre el mismo archivo
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_file(tmp_path):
    """Base SQLite escribible en archivo, para construir el dataset."""
    from app.config.database import bind_database

    path = tmp_path / "monetary_audit.sqlite3"
    writable = SqliteDatabase(str(path))
    bind_database(writable)
    writable.connect(reuse_if_open=True)
    writable.create_tables(ALL_MODELS)
    yield writable, path
    # Los tests de solo lectura reemplazan el proxy por la conexión de auditoría,
    # así que hay que devolverlo a la base escribible antes de borrar el esquema.
    bind_database(writable)
    writable.drop_tables(ALL_MODELS)
    writable.close()


def _run_audit(db_file, **kwargs):
    """Ejecuta el auditor sobre el handle READ-ONLY y devuelve las auditorías."""
    from app.config.database import bind_database
    from app.services.monetary_audit_readonly import (
        MonetaryIntegrityAuditor,
        open_readonly_sqlite,
    )

    _writable, path = db_file
    handle = open_readonly_sqlite(path)
    try:
        return MonetaryIntegrityAuditor(handle.database).run(**kwargs)
    finally:
        handle.close()
        bind_database(_writable)


def _snapshot(path):
    """Huella de las tablas que la auditoría no debe tocar."""
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder, LoadOrderProduct

    models = {
        "Budget": Budget,
        "BudgetItem": BudgetItem,
        "LoadOrder": LoadOrder,
        "LoadOrderProduct": LoadOrderProduct,
        "ClientAccountMovement": ClientAccountMovement,
        "AuditLog": AuditLog,
    }
    assert set(SNAPSHOT_TABLES) == set(models)

    connection = SqliteDatabase(str(path))
    connection.connect(reuse_if_open=True)
    try:
        from app.config.database import bind_database

        bind_database(connection)
        snapshot = {}
        for name, model in models.items():
            digest = sha256()
            rows = list(model.select().order_by(model.id))
            for row in rows:
                payload = json.dumps(
                    {key: str(value) for key, value in sorted(row.__data__.items())},
                    sort_keys=True,
                )
                digest.update(payload.encode("utf-8"))
            snapshot[name] = (len(rows), digest.hexdigest())
        return snapshot
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Constructores de dataset (escriben SOLO en la base de test)
# ---------------------------------------------------------------------------


def _masters():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck

    carrier = Carrier.create(name="Transportista audit", cuit="30777777770")
    driver = Driver.create(name="Chofer audit", carrier=carrier, document="1")
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
    }


def _order(masters, *, order_number=51, number_lines=1):
    from app.models.load_orders import LoadOrder, LoadOrderDestination
    from app.models.masters import Product

    order = LoadOrder.create(
        order_number=order_number,
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
    products = []
    for index in range(number_lines):
        name, quantity, price = CASO_000073[index % len(CASO_000073)]
        suffix = f" {index}" if number_lines > len(CASO_000073) else ""
        products.append(
            {
                "product": Product.create(
                    name=f"{name}{suffix}", unit="bolsa", precio_neto_base=float(price)
                ),
                "quantity": quantity,
                "price": price,
            }
        )
    return order, destination, products


def _order_rows(order, destination, products):
    from app.models.load_orders import LoadOrderProduct
    from app.services.money import compute_line_amounts

    rows = []
    for line in products:
        amounts = compute_line_amounts(
            quantity=line["quantity"],
            unit_price=line["price"],
            discount_percentage="0",
            vat_percentage="0",
        )
        rows.append(
            LoadOrderProduct.create(
                order=order,
                destination=destination,
                product=line["product"],
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
    return rows


def _budget_from_order(order, client, rows, *, budget_number, header_totals=None):
    """Crea el presupuesto con detalle igual al snapshot de la orden.

    ``header_totals`` permite emular la cabecera histórica inconsistente
    (el caso 000073), sin que el detalle se toque.
    """
    from app.models.budgets import Budget, BudgetItem

    detail_net = sum(Decimal(repr(row.neto_subtotal)) for row in rows)
    detail_total = sum(Decimal(repr(row.total)) for row in rows)
    net = detail_net
    total = detail_total
    if header_totals is not None:
        net = Decimal(header_totals.get("net", str(net)))
        total = Decimal(header_totals.get("total", str(total)))

    budget = Budget.create(
        budget_number=budget_number,
        client=client,
        load_order=order,
        origin=Budget.ORIGIN_LOAD_ORDER,
        issue_date=order.date,
        net_amount=float(net),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(total),
        created_by="seed",
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
    return budget


def _ledger_original(order, client, budget, *, total, movement_id_from=0):
    from app.models.accounting import ClientAccountMovement

    amount = Decimal(str(total))
    return ClientAccountMovement.create(
        client=client,
        load_order=order,
        budget=budget,
        payment=None,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=0.0,
        net_amount=float(amount),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(amount),
        currency="ARS",
        movement_date=order.date,
        due_date=order.date,
        description=f"Presupuesto {budget.display_number} / OC-{order.order_number:06d}",
        source_ref=f"Budget:{budget.id}",
        reference=budget.display_number,
        is_reversal=False,
        created_by="seed",
    )


# ---------------------------------------------------------------------------
# 1) DEFENSA TECNICA: LA CONEXION NO PUEDE ESCRIBIR
# ---------------------------------------------------------------------------


WRITE_STATEMENTS = (
    "INSERT INTO budgetitem (id, unit) VALUES (1, 'kg')",
    "UPDATE budget SET total_amount = 0",
    "DELETE FROM budgetitem",
    "REPLACE INTO budgetitem (id) VALUES (1)",
    "CREATE TABLE auditor_tmp (id INTEGER)",
    "ALTER TABLE budget ADD COLUMN tmp INTEGER",
    "DROP TABLE budgetitem",
    "TRUNCATE TABLE clientaccountmovement",
    "RENAME TABLE budget TO budget2",
    "GRANT ALL PRIVILEGES ON femag.* TO 'x'@'%'",
    "REVOKE ALL PRIVILEGES ON femag.* FROM 'x'@'%'",
    "CALL alguna_rupia()",
    "SET GLOBAL max_connections = 1",
    "SET autocommit = 1",
    "LOAD DATA INFILE 'x' INTO TABLE budget",
    "  \n  -- comentario\n  INSERT INTO budget (id) VALUES (9)",
    "/* comentario */ /*!50000 DROP TABLE budgetitem */",
)


@pytest.mark.parametrize("sql", WRITE_STATEMENTS)
def test_la_conexion_de_auditoria_rechaza_todo_verbo_de_escritura(db_file, sql):
    from app.services.monetary_audit_readonly import ReadOnlyViolation, open_readonly_sqlite

    _writable, path = db_file
    handle = open_readonly_sqlite(path)
    try:
        with pytest.raises(ReadOnlyViolation):
            handle.database.execute_sql(sql)
    finally:
        handle.close()


READ_STATEMENTS = (
    "SELECT * FROM budget",
    "  select count(*) from budgetitem",
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "SHOW TABLES",
    "EXPLAIN SELECT 1",
    "DESCRIBE budget",
    "PRAGMA foreign_keys",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT auditor",
    "RELEASE SAVEPOINT auditor",
    "SET SESSION TRANSACTION READ ONLY",
    "START TRANSACTION READ ONLY",
    "-- solo un comentario\nSELECT 1",
    "/* bloque */ WITH t AS (SELECT 2 AS x) SELECT x FROM t",
)


@pytest.mark.parametrize("sql", READ_STATEMENTS)
def test_el_guard_de_sql_permite_los_verbos_de_lectura(sql):
    """El guard no depende del motor: valida el verbo, no el dialecto."""
    from app.services.monetary_audit_readonly import assert_read_only_sql

    assert assert_read_only_sql(sql)


SQLITE_READ_STATEMENTS = (
    "SELECT COUNT(*) FROM budget",
    "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
    "PRAGMA foreign_keys",
)


@pytest.mark.parametrize("sql", SQLITE_READ_STATEMENTS)
def test_la_conexion_de_auditoria_ejecuta_lecturas_reales(db_file, sql):
    from app.services.monetary_audit_readonly import open_readonly_sqlite

    _writable, path = db_file
    handle = open_readonly_sqlite(path)
    try:
        handle.database.execute_sql(sql)
    finally:
        handle.close()


def test_los_modelos_no_pueden_crear_registros_sobre_la_conexion_de_auditoria(db_file):
    from app.services.monetary_audit_readonly import ReadOnlyViolation, open_readonly_sqlite

    from app.models.budgets import Budget

    _writable, path = db_file
    masters = _masters()
    handle = open_readonly_sqlite(path)
    try:
        with pytest.raises(ReadOnlyViolation):
            Budget.create(
                budget_number=999,
                client=masters["client"],
                origin=Budget.ORIGIN_MANUAL,
                net_amount=1.0,
                discount_amount=0.0,
                vat_amount=0.0,
                total_amount=1.0,
            )
    finally:
        handle.close()


def test_el_archivo_se_abre_en_modo_solo_lectura_a_nivel_de_motor(db_file):
    """Defensa de verdad: sin el guard, el propio SQLite rechaza la escritura."""
    from app.config.database import bind_database

    _writable, path = db_file
    _masters()
    writable = SqliteDatabase(str(path))
    bind_database(writable)
    writable.connect(reuse_if_open=True)
    writable.create_tables(ALL_MODELS)
    writable.close()

    raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            raw.execute("INSERT INTO budget (budget_number) VALUES (1234)")
        raw.execute("SELECT budget_number FROM budget").fetchall()
    finally:
        raw.close()


def test_el_auditor_no_usa_el_conector_que_prepara_el_esquema(db_file):
    """El motor de auditoría no es ``FemagMySQLDatabase`` (que migra al conectar)."""
    from app.config.database import FemagMySQLDatabase
    from app.services.monetary_audit_readonly import open_readonly_sqlite

    _writable, path = db_file
    handle = open_readonly_sqlite(path)
    try:
        assert not isinstance(handle.database, FemagMySQLDatabase)
        assert "sqlite_audit_readonly" in handle.protections
        assert "sql_allowlist_guard" in handle.protections
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# 2) NO MUTACION (fase 11)
# ---------------------------------------------------------------------------


def _dataset_000073(db_file, *, ledger_total=CABECERA_000073):
    masters = _masters()
    order, destination, products = _order(masters, number_lines=3)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(
        order,
        masters["client"],
        rows,
        budget_number=73,
        header_totals={"net": str(CABECERA_000073), "total": str(CABECERA_000073)},
    )
    _ledger_original(order, masters["client"], budget, total=ledger_total)
    return masters, order, budget


def test_el_auditor_no_modifica_ninguna_tabla(db_file):
    _writable, path = db_file
    _dataset_000073(db_file)
    antes = _snapshot(path)

    audits = _run_audit(db_file)

    assert len(audits) == 1, "El auditor debe leer el presupuesto persistido"
    despues = _snapshot(path)
    assert despues == antes
    for tabla in SNAPSHOT_TABLES:
        assert despues[tabla][0] == antes[tabla][0], f"{tabla} cambió la cantidad de filas"


def test_auditar_no_crea_presupuestos_ni_movimientos_ausentes(db_file):
    """Sin ``ensure_*``: auditar una orden sin presupuesto no lo genera."""
    from app.models.budgets import Budget

    _writable, path = db_file
    masters = _masters()
    order, destination, products = _order(masters, number_lines=1)
    _order_rows(order, destination, products)
    antes = _snapshot(path)

    audits = _run_audit(db_file)

    assert audits == []
    assert Budget.select().count() == 0
    assert _snapshot(path) == antes


def test_auditar_es_idempotente(db_file):
    _dataset_000073(db_file)

    first = _run_audit(db_file)
    second = _run_audit(db_file)

    assert first == second


# ---------------------------------------------------------------------------
# 3) LECTURA REAL CONTRA EL CASO 000073
# ---------------------------------------------------------------------------


def test_lectura_del_caso_000073_como_ocurrio_en_produccion(db_file):
    _dataset_000073(db_file, ledger_total=CABECERA_000073)

    audit = _run_audit(db_file, budget_number=73)[0]

    assert audit.budget_number == 73
    assert audit.budget_origin == "load_order"
    assert audit.integrity.detail.total == DETALLE_000073
    assert audit.integrity.header.total == CABECERA_000073
    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert audit.integrity.components == ("NET", "TOTAL")
    assert audit.ledger_integrity == LEDGER_MATCH_HEADER
    assert audit.severity == SEVERITY_CRITICAL
    assert audit.budget_header_difference == Decimal("25.00")
    assert audit.ledger.ledger_matches_header is True
    assert audit.ledger.ledger_matches_detail is False
    assert audit.ledger.ledger_detail_difference == Decimal("25.00")
    assert audit.ledger.ledger_header_difference == Decimal("0.00")
    assert audit.potential_financial_difference == Decimal("25.00")
    assert audit.order_budget == ORDER_MATCH
    assert audit.ledger.movement_ids


def test_lectura_con_ledger_igual_al_detalle_es_warning_sin_riesgo(db_file):
    _dataset_000073(db_file, ledger_total=DETALLE_000073)

    audit = _run_audit(db_file, budget_number=73)[0]

    assert audit.budget_integrity == BUDGET_HEADER_MISMATCH
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL
    assert audit.severity == SEVERITY_WARNING
    assert audit.potential_financial_difference == Decimal("0.00")


def test_presupuesto_consistente_desde_orden(db_file):
    masters = _masters()
    order, destination, products = _order(masters, order_number=60, number_lines=2)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=60)
    _ledger_original(order, masters["client"], budget, total=budget.total_amount)

    audit = _run_audit(db_file, budget_number=60)[0]

    assert audit.budget_integrity == STATUS_OK
    assert audit.order_budget == ORDER_MATCH
    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_pago_parcial_no_es_inconsistencia(db_file):
    from app.models.accounting import ClientAccountMovement
    from app.models.payments import ClientPayment

    masters = _masters()
    order, destination, products = _order(masters, order_number=61, number_lines=1)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=61)
    _ledger_original(order, masters["client"], budget, total=budget.total_amount)

    total = Decimal(str(budget.total_amount))
    payment = ClientPayment.create(
        receipt_number="REC-00000001",
        client=masters["client"],
        payment_date=order.date,
        amount=float(total / 2),
        method=ClientPayment.METHOD_TRANSFER,
    )
    ClientAccountMovement.create(
        client=masters["client"],
        load_order=None,
        payment=payment,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        amount=float(-total / 2),
        net_amount=float(-total / 2),
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=float(-total / 2),
        description="Pago parcial",
        source_ref=f"ClientPayment:{payment.id}",
        is_reversal=False,
    )

    audit = _run_audit(db_file, budget_number=61)[0]

    assert audit.ledger_integrity == LEDGER_MATCH_DETAIL_AND_HEADER
    assert audit.ledger.payments.count == 1
    assert audit.ledger.payments.amount == (total / 2).quantize(Decimal("0.01"))
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_reversion_de_operacion_no_es_deuda_incorrecta(db_file):
    from app.models.accounting import ClientAccountMovement

    masters = _masters()
    order, destination, products = _order(masters, order_number=62, number_lines=1)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=62)
    original = _ledger_original(
        order, masters["client"], budget, total=budget.total_amount
    )
    ClientAccountMovement.create(
        client=masters["client"],
        load_order=order,
        budget=budget,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL,
        amount=-original.amount,
        net_amount=-original.net_amount,
        discount_amount=-original.discount_amount,
        vat_amount=-original.vat_amount,
        total_amount=-original.total_amount,
        movement_date=order.date,
        description=f"Reverso {original.description}",
        source_ref=original.source_ref,
        reference=original.reference,
        is_reversal=True,
        reverses=original,
    )

    audit = _run_audit(db_file, budget_number=62)[0]

    assert audit.ledger_integrity == LEDGER_REVERSED
    assert audit.ledger.reversals.amount == -Decimal(str(original.total_amount))
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_orden_editada_despues_del_presupuesto_es_drift(db_file):
    from app.models.load_orders import LoadOrderProduct

    masters = _masters()
    order, destination, products = _order(masters, order_number=63, number_lines=1)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=63)
    _ledger_original(order, masters["client"], budget, total=budget.total_amount)

    row = rows[0]
    nuevo_precio = float(Decimal(str(row.precio_neto_unitario)) * 2)
    row.precio_neto_unitario = nuevo_precio
    row.total = nuevo_precio
    row.neto_subtotal = nuevo_precio
    row.neto_gravado = nuevo_precio
    row.save()

    audit = _run_audit(db_file, budget_number=63)[0]

    assert audit.budget_integrity == STATUS_OK
    assert audit.order_budget == ORDER_DRIFT
    assert audit.order.difference > 0
    assert audit.order.possible_post_budget_change is True
    # El total vigente se recalcula: cantidad x precio nuevo, no el importe viejo.
    assert audit.order.order_total_current == Decimal(str(nuevo_precio * row.quantity))
    assert audit.order.budget_detail_total == Decimal(str(budget.total_amount))
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_varios_movimientos_originales_son_ambiguos(db_file):
    from app.models.accounting import ClientAccountMovement

    masters = _masters()
    order, destination, products = _order(masters, order_number=64, number_lines=1)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=64)
    _ledger_original(order, masters["client"], budget, total=budget.total_amount)
    # Un segundo débito del mismo presupuesto con otra trazabilidad histórica
    # (``source_ref`` estilo ``LoadOrder:<id>``): la base lo permite porque el
    # índice único incluye ``source_ref`` y el auditor no puede decidir cuál vale.
    ClientAccountMovement.create(
        client=masters["client"],
        load_order=order,
        budget=budget,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=0.0,
        net_amount=budget.net_amount,
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=budget.total_amount,
        movement_date=order.date,
        description="Segundo débito sin trazabilidad unificada",
        source_ref=f"LoadOrder:{order.id}",
        reference=None,
        is_reversal=False,
    )

    audit = _run_audit(db_file, budget_number=64)[0]

    assert audit.ledger_integrity == LEDGER_AMBIGUOUS
    assert len(audit.ledger.movement_ids) == 2
    assert audit.severity == SEVERITY_WARNING
    assert audit.potential_financial_difference == Decimal("0.00")


def test_presupuesto_manual_sin_orden_se_audita(db_file):
    from app.models.budgets import Budget, BudgetItem
    from app.models.masters import Product

    masters = _masters()
    product = Product.create(name="Producto manual", unit="bolsa")
    budget = Budget.create(
        budget_number=80,
        client=masters["client"],
        load_order=None,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=masters["client"].created_at.date(),
        net_amount=100.0,
        discount_amount=0.0,
        vat_amount=0.0,
        total_amount=100.0,
    )
    BudgetItem.create(
        budget=budget,
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

    audit = _run_audit(db_file, budget_number=80)[0]

    assert audit.budget_integrity == STATUS_OK
    assert audit.order_budget == ORDER_NO_ORDER
    assert audit.order.order_total_current is None
    assert audit.ledger_integrity == LEDGER_NONE
    assert audit.severity == SEVERITY_INFO


def test_presupuesto_sin_movimiento_de_cuenta_corriente(db_file):
    masters = _masters()
    order, destination, products = _order(masters, order_number=65, number_lines=1)
    rows = _order_rows(order, destination, products)
    _budget_from_order(order, masters["client"], rows, budget_number=65)

    audit = _run_audit(db_file, budget_number=65)[0]

    assert audit.ledger_integrity == LEDGER_NONE
    assert audit.ledger.movement_ids == ()
    assert audit.severity == SEVERITY_INFO
    assert audit.potential_financial_difference == Decimal("0.00")


def test_ledger_que_no_coincide_con_nada_es_critical(db_file):
    masters = _masters()
    order, destination, products = _order(masters, order_number=66, number_lines=1)
    rows = _order_rows(order, destination, products)
    budget = _budget_from_order(order, masters["client"], rows, budget_number=66)
    _ledger_original(order, masters["client"], budget, total="1.00")

    audit = _run_audit(db_file, budget_number=66)[0]

    assert audit.ledger_integrity == LEDGER_MATCH_NEITHER
    assert audit.severity == SEVERITY_CRITICAL
    assert audit.potential_financial_difference > 0


def test_filtro_por_id_de_presupuesto(db_file):
    _dataset_000073(db_file)

    audit = _run_audit(db_file, budget_id=1)[0]

    assert audit.budget_id == 1
    assert audit.budget_number == 73


def test_sin_resultados_no_falla(db_file):
    _writable, path = db_file

    assert _run_audit(db_file) == []
    assert _run_audit(db_file, budget_number=999) == []

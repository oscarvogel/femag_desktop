"""Prueba de que UPDATE, postcondición y AuditLog comparten una sola transacción.

El ``--apply`` falló en producción y la hipótesis inicial era una divergencia
entre la conexión de la reparación y ``database_proxy``. Estos tests atacan esa
hipótesis de forma directa, sin mocks que la oculten:

* BEGIN → UPDATE → SELECT dentro de la misma transacción ⇒ valor nuevo;
* lo mismo para el movimiento original;
* ``verify_postconditions`` lee esos mismos valores nuevos;
* excepción forzada ⇒ rollback ⇒ valores originales restaurados;
* el objeto ``database`` de la transacción es el mismo que resuelve el proxy y
  el mismo que usan los modelos;
* la conexión no cambia a mitad de la transacción.
"""

from decimal import Decimal

import pytest

from app.config.database import database_proxy
from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget
from app.services.monetary_audit import BUDGET_HEADER_MISMATCH, LEDGER_MATCH_HEADER
from scripts.repair_monetary_integrity import (
    RepairAborted,
    _assert_wiring,
    _connection_id,
    apply_plan,
    audit_budget,
    build_plan,
    classify_repair,
    verify_postconditions,
)

from tests.test_repair_monetary_integrity import DETALLE, MOVEMENT_ID_000073, _caso_000073

NUEVO = Decimal("37511775.00")
VIEJO = Decimal("37511800.00")


# ---------------------------------------------------------------------------
# La transacción ve sus propias escrituras
# ---------------------------------------------------------------------------


def test_1_update_y_select_dentro_de_la_misma_transaccion(db):
    database = database_proxy.obj
    _caso_000073()

    with database.atomic():
        assert database.transaction_depth() == 1
        budget = Budget.get_by_id(73)
        budget.net_amount = float(NUEVO)
        budget.total_amount = float(NUEVO)
        budget.save(only=["net_amount", "total_amount"])

        reread = Budget.get_by_id(73)
        assert Decimal(str(reread.total_amount)) == NUEVO
        assert Decimal(str(reread.net_amount)) == NUEVO


def test_2_movimiento_original_visible_dentro_de_la_misma_transaccion(db):
    database = database_proxy.obj
    _caso_000073()

    with database.atomic():
        mov = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
        mov.net_amount = float(NUEVO)
        mov.total_amount = float(NUEVO)
        mov.save(only=["net_amount", "total_amount"])

        reread = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
        assert Decimal(str(reread.total_amount)) == NUEVO


def test_3_verify_postconditions_lee_los_valores_nuevos(db):
    database = database_proxy.obj
    _caso_000073()

    with database.atomic():
        budget = Budget.get_by_id(73)
        budget.net_amount = float(NUEVO)
        budget.total_amount = float(NUEVO)
        budget.save(only=["net_amount", "total_amount"])
        mov = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
        mov.net_amount = float(NUEVO)
        mov.total_amount = float(NUEVO)
        mov.save(only=["net_amount", "total_amount"])

        assert verify_postconditions(73, MOVEMENT_ID_000073) == []


def test_4_excepcion_dentro_de_la_transaccion_revierte(db):
    database = database_proxy.obj
    _caso_000073()

    class _Fallo(RuntimeError):
        pass

    with pytest.raises(_Fallo):
        with database.atomic():
            budget = Budget.get_by_id(73)
            budget.total_amount = float(NUEVO)
            budget.save(only=["total_amount"])
            mov = ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
            mov.total_amount = float(NUEVO)
            mov.save(only=["total_amount"])
            raise _Fallo("simula el fallo de auditoría")

    assert Decimal(str(Budget.get_by_id(73).total_amount)) == VIEJO
    assert (
        Decimal(str(ClientAccountMovement.get_by_id(MOVEMENT_ID_000073).total_amount))
        == VIEJO
    )


# ---------------------------------------------------------------------------
# Un solo objeto de base y una sola conexión
# ---------------------------------------------------------------------------


def test_5_la_transaccion_usa_el_mismo_objeto_que_el_proxy(db):
    _caso_000073()
    database = database_proxy.obj

    with database.atomic():
        _assert_wiring(database, momento="test")

    assert database_proxy.obj is database
    assert Budget._meta.database is database_proxy
    assert Budget._meta.database.obj is database


def test_6_la_conexion_no_cambia_dentro_de_la_transaccion(db):
    database = database_proxy.obj
    _caso_000073()

    with database.atomic():
        antes = _connection_id(database)
        Budget.get_by_id(73)
        ClientAccountMovement.get_by_id(MOVEMENT_ID_000073)
        verify_postconditions(73, MOVEMENT_ID_000073)
        assert _connection_id(database) == antes


def test_7_postcondicion_fuera_de_transaccion_se_detecta(db):
    database = database_proxy.obj
    _caso_000073()

    with pytest.raises(RepairAborted) as exc:
        _assert_wiring(database, momento="fuera")

    assert "fuera de la transacción" in str(exc.value)


def test_8_conexion_divergente_se_detecta(db, monkeypatch):
    from peewee import SqliteDatabase

    database = database_proxy.obj
    _caso_000073()
    otro = SqliteDatabase(":memory:")

    with database.atomic():
        monkeypatch.setattr(database_proxy, "obj", otro)
        with pytest.raises(RepairAborted) as exc:
            _assert_wiring(database, momento="divergencia")

    assert "divergen" in str(exc.value)


# ---------------------------------------------------------------------------
# El rowcount se verifica
# ---------------------------------------------------------------------------


def test_9_save_devuelve_una_fila_afectada(db):
    _caso_000073()

    budget = Budget.get_by_id(73)
    budget.total_amount = float(NUEVO)
    filas = budget.save(only=["total_amount"])

    assert filas == 1


def test_10_apply_plan_completo_pasa_las_invariantes(db):
    _caso_000073()
    plan = build_plan(audit_budget(budget_number=73))

    apply_plan(plan, user="admin")

    assert verify_postconditions(73, MOVEMENT_ID_000073) == []
    assert classify_repair(audit_budget(budget_number=73)).can_repair is False


def test_11_apply_plan_escribe_una_sola_vez_por_tabla(db):
    from app.models.audit import AuditLog

    _caso_000073()
    plan = build_plan(audit_budget(budget_number=73))

    apply_plan(plan, user="admin")

    assert AuditLog.select().count() == 1
    assert Decimal(str(Budget.get_by_id(73).total_amount)) == NUEVO
    assert (
        Decimal(str(ClientAccountMovement.get_by_id(MOVEMENT_ID_000073).total_amount))
        == NUEVO
    )


def test_12_la_postcondicion_ve_lo_que_esta_por_commitirse(db):
    """Antes del commit, la fila todavía puede estar sin confirmar."""
    database = database_proxy.obj
    _caso_000073()
    plan = build_plan(audit_budget(budget_number=73))
    observados = {}

    original = verify_postconditions

    def _observando(budget_id, movement_id):
        observados["budget"] = Decimal(str(Budget.get_by_id(budget_id).total_amount))
        observados["movement"] = Decimal(
            str(ClientAccountMovement.get_by_id(movement_id).total_amount)
        )
        return original(budget_id, movement_id)

    import scripts.repair_monetary_integrity as modulo

    modulo.verify_postconditions = _observando
    try:
        apply_plan(plan, user="admin")
    finally:
        modulo.verify_postconditions = original

    assert observados["budget"] == NUEVO
    assert observados["movement"] == NUEVO

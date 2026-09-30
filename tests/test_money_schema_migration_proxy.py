"""Regresión del arranque congelado: ``Cannot use uninitialized Proxy``.

El bug NO lo detectaron los tests anteriores porque el fixture de
``test_money_schema_migration_task`` monkeypatcheaba ``_historical_summary``,
justo la función que reventaba. Estos tests usan el proxy real.

Escenario exacto que falló en el EXE compilado contra ``femag_desktop`` ya
migrada a 30/30 DECIMAL(18,2)::

    columns pending before: 0
    columns DECIMAL(18,2) exact: 0/30
    message: AttributeError: Cannot use uninitialized Proxy.

``pending`` daba 0 porque el precheck es SQL crudo sobre un ``MySQLDatabase``
propio (no necesita proxy); el siguiente paso pedía los históricos por modelos,
que sí pasan por ``database_proxy`` sin inicializar.
"""

from decimal import Decimal

import pytest
from peewee import MySQLDatabase

from app.config.money_columns import MONEY_COLUMNS
from app.services import money_schema_migration as tarea

# Se importa de forma explícita y ANTES de parchear ``peewee.MySQLDatabase``:
# el módulo define ``class ReadOnlyMySQLDatabase(..., MySQLDatabase)`` y un doble
# global rompería esa herencia por conflicto de metaclase.
import app.services.monetary_audit_readonly as _readonly  # noqa: F401


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = list(rows) if rows is not None else ([row] if row is not None else [])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def close(self):
        return None


class FakeMySQL(MySQLDatabase):
    def __init__(self, *, migrada):
        super().__init__("femag_fake")
        tipo = "decimal(18,2)" if migrada else "float"
        self.tipos = {(c.table, c.column): tipo for c in MONEY_COLUMNS}
        self.alters = []

    def connect(self, *a, **k):
        return True

    def close(self):
        return True

    def execute_sql(self, sql, params=None):
        plano = " ".join(sql.split())
        if plano.startswith("SELECT COUNT(*) FROM information_schema.TABLES"):
            return _Result((1,))
        if plano.startswith("SELECT COLUMN_TYPE"):
            return _Result((self.tipos.get((params[0], params[1])),))
        if plano.startswith("SELECT COLUMN_NAME, DATA_TYPE"):
            tabla = params[0]
            return _Result(
                rows=[
                    (
                        c.column,
                        "decimal"
                        if self.tipos.get((tabla, c.column), "").startswith("decimal")
                        else "float",
                    )
                    for c in MONEY_COLUMNS
                    if c.table == tabla
                ]
            )
        if plano.startswith("SELECT COUNT(*), SUM(CASE WHEN"):
            return _Result((10, 0, Decimal("0.00"), Decimal("1000.00"), 0, 0))
        if plano.startswith("ALTER TABLE"):
            self.alters.append(plano)
            tabla = plano.split("ALTER TABLE `")[1].split("`")[0]
            columna = plano.split("MODIFY COLUMN `")[1].split("`")[0]
            self.tipos[(tabla, columna)] = "decimal(18,2)"
            return _Result(None)
        if plano.startswith("SELECT `t1`"):
            # Consulta por modelos (``Budget.select()`` y similares) contra una
            # base migrada y sin documentos. Es el camino que exige el proxy.
            return _Result(rows=[])
        raise AssertionError(f"SQL no contemplado: {plano}")


class _Target:
    engine = "mysql"
    host = "127.0.0.1"
    port = 3306
    database = "femag_desktop"
    user = "femag"
    password = "no-imprimir"


@pytest.fixture()
def mysql(monkeypatch):
    """Convierte todo ``MySQLDatabase`` de la tarea en un doble en memoria."""
    base = FakeMySQL(migrada=True)
    monkeypatch.setattr("peewee.MySQLDatabase", lambda *a, **k: base)

    monkeypatch.setattr(_readonly, "resolve_audit_database", lambda: _Target())
    monkeypatch.setattr(
        tarea,
        "_make_backup",
        lambda target, runtime_dir: tarea.DatabaseDump(
            target.database, str(runtime_dir / "b.sql"), "success"
        ),
    )
    return base


@pytest.fixture()
def proxy_sin_inicializar():
    """Reproduce el arranque real: el proxy todavía NO fue inicializado.

    Es la diferencia clave contra los tests anteriores: They'd enlazaban el
    proxy a un SQLite, así que el bug quedaba tapado. Acá el proxy arranca
    vacío, igual que en el EXE congelado.
    """
    from app.config.database import database_proxy

    database_proxy.initialize(None)
    return database_proxy


# ---------------------------------------------------------------------------
# Qué proxy era y por qué fallaba
# ---------------------------------------------------------------------------


def test_los_modelos_de_femag_usan_el_proxy_no_una_base_directa():
    """Identifica el proxy implicado: ``app/models/base.py`` lo asigna a ``Meta``."""
    from app.config.database import database_proxy
    from app.models.budgets import Budget

    assert isinstance(database_proxy, type(database_proxy))
    assert Budget._meta.database is database_proxy


def test_consultar_un_modelo_sin_proxy_inicializado_da_el_error_del_exe():
    """Reproduce el mensaje exacto del EXE, sin adivinarlo."""
    from peewee import DatabaseProxy

    from app.models.budgets import Budget

    proxy = DatabaseProxy()
    original = Budget._meta.database
    Budget._meta.database = proxy
    try:
        with pytest.raises(AttributeError) as exc:
            Budget.select().count()
        assert "uninitialized Proxy" in str(exc.value)
    finally:
        Budget._meta.database = original


# ---------------------------------------------------------------------------
# El fix
# ---------------------------------------------------------------------------


def test_la_tarea_enlaza_el_proxy_antes_de_consultar_modelos(mysql):
    from app.config.database import database_proxy

    tarea._open_writable(_Target())

    assert database_proxy.obj is not None, "el proxy quedaría sin inicializar"


def test_la_conexion_de_la_tarea_es_la_misma_que_usa_el_proxy(mysql):
    """SQL crudo y modelos no pueden vivir en conexiones distintas."""
    from app.config.database import database_proxy
    from app.models.budgets import Budget

    database = tarea._open_writable(_Target())

    assert database_proxy.obj is database
    assert Budget._meta.database.obj is database


# ---------------------------------------------------------------------------
# El caso exacto del EXE: base ya migrada
# ---------------------------------------------------------------------------


def test_base_ya_migrada_reporta_30_de_30_y_no_altera(tmp_path, mysql, proxy_sin_inicializar):
    """pending=0, exact=30, altered=0: abre normal, sin backup ni ALTER."""
    base = mysql

    reporte = tarea.ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == tarea.STATUS_SKIPPED, reporte.message
    assert reporte.columns_pending_before == 0
    assert reporte.columns_exact_decimal == 30
    assert reporte.columns_altered == 0
    assert base.alters == []


def test_base_ya_migrada_no_falla_por_proxy(mysql, proxy_sin_inicializar, tmp_path):
    """Si el proxy no estuviera enlazado, esto daría STATUS_FAILED."""
    reporte = tarea.ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status != tarea.STATUS_FAILED, reporte.message


def test_base_en_float_migra_y_llega_a_30_de_30(tmp_path, mysql, proxy_sin_inicializar):
    base = mysql
    for c in MONEY_COLUMNS:
        base.tipos[(c.table, c.column)] = "float"

    reporte = tarea.ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == tarea.STATUS_OK, reporte.message
    assert reporte.columns_pending_before == 30
    assert reporte.columns_altered == 30
    assert reporte.columns_exact_decimal == 30
    assert base.alters

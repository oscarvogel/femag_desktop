"""La migración de columnas monetarias NUNCA corre al abrir FEMAG.

Son 30 ``ALTER TABLE ... MODIFY COLUMN`` sobre importes. Eso tiene que ser una
operación explícita, con precheck y confirmación humana, no un efecto colateral
de abrir la aplicación.

Estos tests fijan esa frontera:

* el arranque de la app no altera columnas monetarias;
* el comando administrativo sin ``--apply`` no escribe nada;
* ``--apply`` exige un precheck verde;
* un precheck fallido no ejecuta ningún ALTER;
* una segunda ejecución es idempotente e informa ALREADY MIGRATED.
"""

from decimal import Decimal

import pytest
from peewee import MySQLDatabase

from app.config.money_columns import (
    MONEY_COLUMNS,
    MoneyMigrationAbort,
    precheck_money_columns,
)
from scripts.migrate_money_columns import (
    ALREADY_MIGRATED,
    run_migration,
)


class _Result:
    """Cursor mínimo: guarda la fila de ``fetchone`` y la lista de ``fetchall``."""

    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = list(rows) if rows is not None else ([row] if row is not None else [])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeMySQL(MySQLDatabase):
    """MySQLDatabase real con ``execute_sql`` sustituido. No abre conexión."""

    def __init__(self, *, tipos=None, fuera_de_rango=()):
        super().__init__("femag_fake")
        self.tipos = dict(tipos or {})
        self.fuera_de_rango = set(fuera_de_rango)
        self.ejecutadas: list[str] = []
        self.abiertas = 0
        self.cerradas = 0

    def connect(self, *args, **kwargs):
        self.abiertas += 1
        return True

    def close(self):
        self.cerradas += 1
        return True

    @property
    def alters(self):
        return [s for s in self.ejecutadas if s.strip().upper().startswith("ALTER TABLE")]

    def execute_sql(self, sql, params=None):
        self.ejecutadas.append(sql)
        plano = " ".join(sql.split())
        if plano.startswith("SELECT COUNT(*) FROM information_schema.TABLES"):
            return _Result((1,))
        if plano.startswith("SELECT COLUMN_TYPE"):
            tipo = self.tipos.get((params[0], params[1]))
            return _Result((tipo,))
        if plano.startswith("SELECT COLUMN_NAME, DATA_TYPE"):
            tabla = params[0]
            return _Result(
                rows=[
                    (col, "decimal" if self.tipos.get((tabla, col)) == "decimal" else "float")
                    for col in self._columnas_de(tabla)
                ]
            )
        if plano.startswith("SELECT COUNT(*), SUM(CASE WHEN"):
            tabla = plano.split("FROM `")[1].split("`")[0]
            nombre = plano.split("WHEN `")[1].split("`")[0]
            fuera = 1 if (tabla, nombre) in self.fuera_de_rango else 0
            return _Result((10, 0, Decimal("0.00"), Decimal("1000.00"), fuera, 0))
        if plano.startswith("ALTER TABLE"):
            tabla = plano.split("ALTER TABLE `")[1].split("`")[0]
            columna = plano.split("MODIFY COLUMN `")[1].split("`")[0]
            self.tipos[(tabla, columna)] = "decimal(18,2)"
            return _Result(None)
        raise AssertionError(f"SQL no contemplado: {plano}")

    def _columnas_de(self, tabla):
        return [c.column for c in MONEY_COLUMNS if c.table == tabla]


@pytest.fixture()
def todas_float():
    base = FakeMySQL(tipos={(c.table, c.column): "float" for c in MONEY_COLUMNS})
    return base


@pytest.fixture()
def todas_decimal():
    base = FakeMySQL(
        tipos={(c.table, c.column): "decimal(18,2)" for c in MONEY_COLUMNS}
    )
    return base


# ---------------------------------------------------------------------------
# 1) Abrir FEMAG no migra columnas monetarias
# ---------------------------------------------------------------------------


def test_app_startup_no_ejecuta_la_migracion_monetaria(todas_float, monkeypatch):
    """``ensure_runtime_schema`` no debe tocar ni una columna de dinero."""
    from app.config import schema as schema_module

    base = todas_float
    # Se aíslan los pasos que no son el objeto del test; lo que se verifica es
    # que el arranque no invoca la migración de columnas monetarias.
    monkeypatch.setattr(schema_module, "_ensure_model_columns", lambda db, model: None)
    for nombre in (
        "_backfill_client_emails",
        "_backfill_product_classification",
        "_normalize_legacy_pallet_rows",
        "_consolidate_shared_client_addresses",
        "_repair_payment_movement_amounts",
        "_ensure_pallet_sequence_index",
        "_ensure_account_movement_source_index",
        "_ensure_client_salesperson_index",
        "_ensure_sqlite_index_integrity",
    ):
        monkeypatch.setattr(schema_module, nombre, lambda db: None)
    base.create_tables = lambda models, safe=True: None

    schema_module.ensure_runtime_schema(base)

    assert base.alters == [], (
        "abrir la aplicación no puede alterar columnas monetarias: "
        + "; ".join(base.alters)
    )


def test_el_modulo_schema_no_declara_migracion_de_dinero():
    """La función se elimino del arranque, no quedo como no-op."""
    from app.config import schema as schema_module

    assert not hasattr(schema_module, "_migrate_money_columns")
    assert "money_columns" not in _source_of_ensure_runtime_schema()


def _source_of_ensure_runtime_schema() -> str:
    import inspect

    from app.config import schema as schema_module

    return inspect.getsource(schema_module.ensure_runtime_schema)


# ---------------------------------------------------------------------------
# 2) El comando sin --apply no escribe
# ---------------------------------------------------------------------------


def test_comando_sin_apply_no_escribe_nada(todas_float, capsys):
    codigo = run_migration([], open_database=lambda target: todas_float)

    salida = capsys.readouterr().out
    assert codigo == 0
    assert "PRECHECK ONLY: no se modificó nada." in salida
    assert todas_float.alters == [], "sin --apply no debe haber ningún ALTER"
    assert "MONEY COLUMN MIGRATION PLAN" in salida
    assert "Columnas a migrar           : 30" in salida


def test_el_plan_muestra_lo_pedido_antes_de_alterar(todas_float, capsys):
    run_migration([], open_database=lambda target: todas_float)

    salida = capsys.readouterr().out
    assert "Columnas registradas        : 30" in salida
    assert "Valores fuera del destino   : 0" in salida
    assert "Valores que se cuantizarán" in salida
    assert "budget" in salida and "total_amount" in salida
    assert "clientaccountmovement" in salida and "net_amount" in salida


# ---------------------------------------------------------------------------
# 3) --apply exige precheck verde
# ---------------------------------------------------------------------------


def test_apply_ejecuta_los_alters_cuando_el_precheck_pasa(todas_float, capsys):
    codigo = run_migration(["--apply"], open_database=lambda target: todas_float)

    salida = capsys.readouterr().out
    assert codigo == 0
    assert len(todas_float.alters) == 30
    assert all("MODIFY COLUMN" in s for s in todas_float.alters)
    assert all("DECIMAL(18,2)" in s for s in todas_float.alters)
    assert "MIGRATED" in salida
    assert "Columnas alteradas: 30" in salida


def test_apply_aborta_si_el_precheck_falla(capsys):
    objetivo = MONEY_COLUMNS[0]
    base = FakeMySQL(
        tipos={(c.table, c.column): "float" for c in MONEY_COLUMNS},
        fuera_de_rango={(objetivo.table, objetivo.column)},
    )

    codigo = run_migration(["--apply"], open_database=lambda target: base)

    capturado = capsys.readouterr()
    assert codigo == 3
    assert "ABORTED" in capturado.err
    assert "No se ejecutó ningún ALTER." in capturado.err
    assert base.alters == [], "un precheck fallido no puede alterar nada"


def test_precheck_fallido_tampoco_altera_sin_apply(capsys):
    objetivo = MONEY_COLUMNS[0]
    base = FakeMySQL(
        tipos={(c.table, c.column): "float" for c in MONEY_COLUMNS},
        fuera_de_rango={(objetivo.table, objetivo.column)},
    )

    codigo = run_migration([], open_database=lambda target: base)

    assert codigo == 3
    assert base.alters == []


# ---------------------------------------------------------------------------
# 4) Idempotencia
# ---------------------------------------------------------------------------


def test_si_ya_esta_migrada_no_hace_alter(todas_decimal, capsys):
    codigo = run_migration(["--apply"], open_database=lambda target: todas_decimal)

    salida = capsys.readouterr().out
    assert codigo == 0
    assert ALREADY_MIGRATED in salida
    assert todas_decimal.alters == [], "ya migrada no debe ejecutar ningún ALTER"


def test_segunda_ejecucion_es_idempotente(todas_float, capsys):
    primera = run_migration(["--apply"], open_database=lambda target: todas_float)
    capsys.readouterr()
    alters_primera = len(todas_float.alters)

    segunda = run_migration(["--apply"], open_database=lambda target: todas_float)
    salida = capsys.readouterr().out

    assert primera == 0
    assert segunda == 0
    assert len(todas_float.alters) == alters_primera, "la segunda no debe alterar"
    assert ALREADY_MIGRATED in salida


def test_el_precheck_tambien_es_idempotente(todas_decimal, capsys):
    codigo = run_migration([], open_database=lambda target: todas_decimal)

    salida = capsys.readouterr().out
    assert codigo == 0
    assert "Pendientes de migrar: 0" in salida
    assert "Ya en DECIMAL exacto  : 30" in salida
    assert todas_decimal.alters == []


# ---------------------------------------------------------------------------
# Verificación posterior
# ---------------------------------------------------------------------------


def test_verifica_information_schema_despues_de_aplicar(todas_float, capsys):
    run_migration(["--apply"], open_database=lambda target: todas_float)

    salida = capsys.readouterr().out
    assert "VERIFY (information_schema)" in salida
    assert "Columnas a migrar      : 0" in salida
    assert "DECIMAL exacto         : 30" in salida


def test_cierra_la_conexion_que_abrio(todas_float):
    """El comando cierra siempre lo que abrió, incluso si algo falla."""
    run_migration([], open_database=lambda target: todas_float)

    assert todas_float.cerradas == 1


def test_aborta_si_la_configuracion_no_es_mysql(capsys):
    """SQLite no tiene este problema de precisión: no se toca."""
    from app.services.monetary_audit_readonly import AuditDatabaseTarget

    objetivo = AuditDatabaseTarget(engine="sqlite", sqlite_path="x.sqlite3")

    from scripts.migrate_money_columns import open_admin_database

    with pytest.raises(MoneyMigrationAbort):
        open_admin_database(objetivo)


def test_la_conexion_administrativa_no_es_el_conector_de_la_app():
    """Un comando admin no debe disparar ensure_runtime_schema al conectar.

    Se verifica sobre la clase que construye ``open_admin_database``: un
    ``MySQLDatabase`` pelado, no ``FemagMySQLDatabase`` (que migra el esquema y
    siembra medios de pago al abrir).
    """
    import inspect

    from app.config.database import FemagMySQLDatabase
    from scripts.migrate_money_columns import open_admin_database

    fuente = inspect.getsource(open_admin_database)

    assert "MySQLDatabase(" in fuente
    assert "FemagMySQLDatabase" not in fuente
    assert issubclass(FemagMySQLDatabase, MySQLDatabase)

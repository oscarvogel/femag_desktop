"""La migración monetaria corre exactamente una vez durante la actualización.

Y no hace nada más: no repara documentos históricos.

Estos tests fijan el comportamiento de
``app.services.money_schema_migration.ensure_money_schema_migrated`` con dobles
de base y de backup. No tocan ninguna base real.
"""

import json
from decimal import Decimal

import pytest
from peewee import MySQLDatabase

from app.config.money_columns import MONEY_COLUMNS
from app.services import money_schema_migration as tarea
from app.services.money_schema_migration import (
    STATUS_ABORTED,
    STATUS_OK,
    STATUS_SKIPPED,
    ensure_money_schema_migrated,
)


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = list(rows) if rows is not None else ([row] if row is not None else [])

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeMySQL(MySQLDatabase):
    """MySQLDatabase real con ``execute_sql`` sustituido."""

    def __init__(self, *, tipos, fuera=0):
        super().__init__("femag_fake")
        self.tipos = dict(tipos)
        self.fuera = fuera
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
            tabla = plano.split("FROM `")[1].split("`")[0]
            nombre = plano.split("WHEN `")[1].split("`")[0]
            return _Result((10, 0, Decimal("0.00"), Decimal("1000.00"), self.fuera, 0))
        if plano.startswith("ALTER TABLE"):
            self.alters.append(plano)
            tabla = plano.split("ALTER TABLE `")[1].split("`")[0]
            columna = plano.split("MODIFY COLUMN `")[1].split("`")[0]
            self.tipos[(tabla, columna)] = "decimal(18,2)"
            return _Result(None)
        raise AssertionError(f"SQL no contemplado: {plano}")


class _Target:
    def __init__(self, engine="mysql"):
        self.engine = engine
        self.host = "10.0.0.9"
        self.port = 3306
        self.database = "femag_desktop"
        self.user = "femag"
        self.password = "no-imprimir"


def _base(pendientes, fuera=0):
    tipo = "float" if pendientes else "decimal(18,2)"
    return FakeMySQL(tipos={(c.table, c.column): tipo for c in MONEY_COLUMNS}, fuera=fuera)


@pytest.fixture(autouse=True)
def _aislar(monkeypatch):
    """Ni el conteo de históricos ni el backup tocan nada en estos tests."""
    import app.services.monetary_audit_readonly as readonly

    monkeypatch.setattr(readonly, "resolve_audit_database", lambda: _Target())
    monkeypatch.setattr(tarea, "_historical_summary", lambda database: (3, 1, "25.00"))
    monkeypatch.setattr(
        tarea,
        "_make_backup",
        lambda target, runtime_dir: tarea.DatabaseDump(
            target.database, str(runtime_dir / "backup.sql"), "success"
        ),
    )


# ---------------------------------------------------------------------------
# Exactamente una vez
# ---------------------------------------------------------------------------


def test_migra_una_sola_vez_y_luego_es_idempotente(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    primera = ensure_money_schema_migrated(runtime_dir=tmp_path, build_version="test")

    assert primera.status == STATUS_OK
    assert primera.columns_pending_before == 30
    assert primera.columns_altered == 30
    assert primera.columns_pending_after == 0
    assert primera.columns_exact_decimal == 30
    assert len(base.alters) == 30

    segunda = ensure_money_schema_migrated(runtime_dir=tmp_path, build_version="test")

    assert segunda.status == STATUS_SKIPPED
    assert segunda.columns_altered == 0
    assert len(base.alters) == 30, "el segundo arranque no debe alterar nada"
    assert "ya migrado" in (segunda.message or "")


def test_un_esquema_ya_migrado_no_altera_nada(tmp_path, monkeypatch):
    base = _base(False)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_SKIPPED
    assert base.alters == []


def test_el_recibo_audita_la_migracion_sin_mandar_password(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    ensure_money_schema_migrated(runtime_dir=tmp_path, build_version="2026.09.30")

    recibo = tarea.receipt_path(tmp_path)
    assert recibo.exists()
    datos = json.loads(recibo.read_text(encoding="utf-8"))
    assert datos["task"] == "money_columns_float_to_decimal"
    assert datos["build_version"] == "2026.09.30"
    assert datos["columns_altered"] == 30
    assert datos["status"] == STATUS_OK
    assert datos["user"] == "femag"
    assert "no-imprimir" not in recibo.read_text(encoding="utf-8")


def test_borrar_el_recibo_no_reejecuta_los_alter(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)
    ensure_money_schema_migrated(runtime_dir=tmp_path)
    tarea.receipt_path(tmp_path).unlink()

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_SKIPPED
    assert len(base.alters) == 30


# ---------------------------------------------------------------------------
# Abortajes: si algo no está bien, no se altera nada
# ---------------------------------------------------------------------------


def test_aborta_sin_alterar_si_hay_valores_fuera_de_rango(tmp_path, monkeypatch):
    base = _base(True, fuera=3)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)
    intentos = []
    monkeypatch.setattr(
        tarea,
        "_make_backup",
        lambda target, runtime_dir: intentos.append(1) or tarea.DatabaseDump(
            target.database, None, "error", "sin disco"
        ),
    )

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_ABORTED
    assert base.alters == [], "con valores fuera de rango no se altera nada"
    assert intentos == [], "con valores fuera de rango ni se intenta respaldar"
    # El doble marca 3 valores fuera de rango en cada una de las 30 columnas.
    assert reporte.values_out_of_range == 90


def test_aborta_sin_alterar_si_el_respaldo_falla(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)
    monkeypatch.setattr(
        tarea,
        "_make_backup",
        lambda target, runtime_dir: tarea.DatabaseDump(
            target.database, None, "error", "mysqldump fallo"
        ),
    )

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_ABORTED
    assert base.alters == [], "sin respaldo no se altera nada"
    assert "respaldo" in (reporte.message or "").lower()


def test_informa_migracion_parcial_y_la_reanuda_al_reabrir(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)
    original = base.execute_sql

    def _una_columna_se_olvida(sql, params=None):
        plano = " ".join(sql.split())
        if plano.startswith("ALTER TABLE"):
            base.alters.append(plano)
            if len(base.alters) == 1:
                return _Result(None)
        return original(sql, params)

    base.execute_sql = _una_columna_se_olvida
    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_ABORTED
    # Se emitieron los 30 ALTER, pero la verificación detectó que uno no tomó
    # efecto: eso es una migración parcial y NO se declara OK.
    assert reporte.columns_altered == 30
    assert reporte.columns_pending_after == 1
    assert "PARCIAL" in (reporte.message or "")

    base.execute_sql = original
    segundo = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert segundo.status == STATUS_OK
    assert segundo.columns_pending_after == 0
    assert segundo.columns_exact_decimal == 30


def test_no_migra_si_la_configuracion_no_es_mysql(tmp_path, monkeypatch):
    import app.services.monetary_audit_readonly as readonly

    monkeypatch.setattr(readonly, "resolve_audit_database", lambda: _Target("sqlite"))
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert reporte.status == STATUS_SKIPPED
    assert base.alters == []


# ---------------------------------------------------------------------------
# NO repara históricos
# ---------------------------------------------------------------------------


def test_no_repara_ningun_documento_historico(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)

    assert len(base.alters) == 30
    for sql in base.alters:
        assert sql.upper().startswith("ALTER TABLE")
        assert "UPDATE" not in sql.upper()
        assert "DELETE" not in sql.upper()
    assert reporte.historical_mismatches == 3
    assert reporte.historical_critical == 1
    assert reporte.historical_potential == "25.00"


def test_el_log_aclara_que_los_historicos_no_se_reparan(tmp_path, monkeypatch):
    base = _base(True)
    monkeypatch.setattr(tarea, "_open_writable", lambda target: base)

    reporte = ensure_money_schema_migrated(runtime_dir=tmp_path)
    texto = "\n".join(reporte.summary_lines())

    assert "NO reparados automaticamente" in texto
    assert "historical critical cases: 1" in texto
    assert "potential financial difference: $25.00" in texto


def test_la_tarea_no_importa_la_herramienta_de_reparacion():
    """Si la tarea importara repair, la reparacion historica dejaria de ser manual."""
    import inspect

    fuente = inspect.getsource(tarea)
    assert "repair_monetary_integrity" not in fuente
    assert "apply_plan" not in fuente

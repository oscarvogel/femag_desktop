"""Pruebas del registro monetario, el diagnÃ³stico previo y la migraciÃ³n.

No tocan ninguna base real: el diagnÃ³stico y la migraciÃ³n se ejercitan contra
un doble de base que responde SQL parametrizado y registra lo que se ejecutarÃ­a.
El caso de MySQL real queda en ``test_money_columns_mysql.py``, que se omite
salvo que se autorice una base temporal.
"""

from decimal import Decimal

import pytest
from peewee import MySQLDatabase

from app.config.money_columns import (
    MONEY_COLUMNS,
    MONEY_COLUMNS_BY_TABLE,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    NON_MONEY_FLOAT_COLUMNS,
    ColumnStats,
    MoneyColumn,
    MoneyMigrationAbort,
    current_column_type,
    default_str,
    is_exact_decimal,
    money_field,
    needs_decimal_migration,
    table_exists,
)


# ---------------------------------------------------------------------------
# Doble de base: responde el SQL del diagnÃ³stico y registra los ALTER
# ---------------------------------------------------------------------------


class _Result:
    """Cursor mÃ­nimo con ``fetchone``, como el que devuelve pymysql."""

    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeMySQL(MySQLDatabase):
    """MySQLDatabase real con ``execute_sql`` sustituido.

    Es un ``MySQLDatabase`` de verdad para que la migraciÃ³n no haga no-op, pero
    no abre ninguna conexiÃ³n: responde el SQL del diagnÃ³stico y registra lo que
    se ejecutarÃ­a.
    """

    def __init__(self, columns=None, stats=None):
        super().__init__("femag_fake")
        # {tabla: {columna: "float"}}
        self.columns = columns or {}
        # {(tabla, columna): (filas, nulos, min, max, fuera_de_rango, fuera_de_escala)}
        self.stats = stats or {}
        self.tables = {t for t, cols in self.columns.items()}
        self.executed: list[str] = []
        self.params: list[tuple] = []

    def execute_sql(self, sql, params=None):
        self.executed.append(sql)
        self.params.append(params)
        plano = " ".join(sql.split())

        if plano.startswith("SELECT COUNT(*) FROM information_schema.TABLES"):
            tabla = params[0]
            return _Result((1 if tabla in self.tables else 0,))
        if plano.startswith("SELECT COLUMN_TYPE"):
            tabla, columna = params
            tipo = self.columns.get(tabla, {}).get(columna)
            return _Result((tipo,)) if tipo else _Result(None)
        if plano.startswith("SELECT COUNT(*), SUM(CASE WHEN"):
            from app.config.money_columns import _escape

            tabla = plano.split("FROM `")[1].split("`")[0]
            nombre = plano.split("WHEN `")[1].split("`")[0]
            return _Result(self.stats.get((tabla, nombre), (0, 0, None, None, 0, 0)))
        if plano.startswith("ALTER TABLE"):
            return _Result(None)
        raise AssertionError(f"SQL no contemplado por el doble: {plano}")


# ---------------------------------------------------------------------------
# El registro cubre exactamente el dinero y excluye lo que no lo es
# ---------------------------------------------------------------------------


def test_el_registro_cubre_las_cuatro_tablas_del_incidente():
    tablas = set(MONEY_COLUMNS_BY_TABLE)
    assert {"budget", "budgetitem", "clientaccountmovement", "loadorderproduct"} <= tablas


def test_el_registro_no_deja_doble():
    pares = [(c.table, c.column) for c in MONEY_COLUMNS]
    assert len(pares) == len(set(pares))


def test_toda_columna_monetaria_usa_la_politica_de_dos_decimales():
    for columna in MONEY_COLUMNS:
        assert columna.decimal_places == MONEY_DECIMAL_PLACES
        assert columna.max_digits == MONEY_MAX_DIGITS
        assert columna.decimal_type == "DECIMAL(18,2)"


def test_no_se_migran_cantidades_porcentajes_ni_pesos():
    importes = {(c.table, c.column) for c in MONEY_COLUMNS}
    for tabla, columnas in NON_MONEY_FLOAT_COLUMNS.items():
        for columna in columnas:
            assert (tabla, columna) not in importes, f"{tabla}.{columna} no es dinero"


def test_los_costos_unitarios_no_entan_en_la_migracion():
    """Ya son DECIMAL(14,4) por decisiÃ³n comercial: no se tocan."""
    columnas = {c.column for c in MONEY_COLUMNS}
    for fuera in ("costo_unitario", "costo_unitario_aplicado", "previous_cost", "new_cost"):
        assert fuera not in columnas


def test_cubre_las_cinco_columnas_del_movimiento_contable():
    del_movimiento = {
        c.column for c in MONEY_COLUMNS_BY_TABLE["clientaccountmovement"]
    }
    assert del_movimiento == {
        "amount",
        "net_amount",
        "discount_amount",
        "vat_amount",
        "total_amount",
    }


# ---------------------------------------------------------------------------
# PolÃ­tica de precisiÃ³n
# ---------------------------------------------------------------------------


def test_decimal_18_2_alcanza_el_maximo_observado_en_produccion():
    objetivo = MoneyColumn("budget", "total_amount")
    maximo_produccion = Decimal("2910410000.00")
    assert objetivo.max_value > maximo_produccion


def test_el_margen_es_de_varios_millones_de_veces():
    objetivo = MoneyColumn("budget", "total_amount")
    assert objetivo.max_value / Decimal("2910410000") > Decimal(1000)


def test_is_exact_decimal_detecta_el_ruido_de_float():
    assert is_exact_decimal(Decimal("37511775.00"))
    assert not is_exact_decimal(Decimal("38619.80078125"))


def test_default_str_es_un_decimal_valido():
    assert default_str(2) == "0.00"
    assert default_str(4) == "0.0000"


def test_money_field_devuelve_decimalfield_con_default_decimal():
    campo = money_field()
    assert campo.max_digits == 18
    assert campo.decimal_places == 2
    assert campo.auto_round is False
    assert isinstance(campo.default, Decimal)
    assert campo.default == Decimal("0.00")


# ---------------------------------------------------------------------------
# DetecciÃ³n de tipo actual
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "actual,target_digits,target_places,espera",
    [
        ("float", 18, 2, True),
        ("double", 18, 2, True),
        ("real", 18, 2, True),
        ("decimal(18,2)", 18, 2, False),
        ("decimal(18,4)", 18, 2, True),
        ("decimal(10,2)", 18, 2, True),
        ("decimal(18,0)", 18, 2, True),
        (None, 18, 2, False),
    ],
)
def test_needs_decimal_migration(actual, target_digits, target_places, espera):
    objetivo = MoneyColumn("budget", "total_amount", target_digits, target_places)
    assert needs_decimal_migration(actual, objetivo) is espera


def test_double_tambien_se_migra_aunque_guarde_algunos_valores():
    """DOUBLE tampoco es el contrato de escala fija que buscamos."""
    objetivo = MoneyColumn("budget", "total_amount")
    assert needs_decimal_migration("double", objetivo) is True


# ---------------------------------------------------------------------------
# DiagnÃ³stico previo
# ---------------------------------------------------------------------------


def _base_con_todas_float():
    columnas = {
        tabla: {columna.column: "float" for columna in group}
        for tabla, group in MONEY_COLUMNS_BY_TABLE.items()
    }
    stats = {}
    for columna in MONEY_COLUMNS:
        stats[(columna.table, columna.column)] = (
            85,
            0,
            Decimal("0.00"),
            Decimal("2910410000.00"),
            0,
            0,
        )
    return FakeMySQL(columns=columnas, stats=stats)


def test_precheck_no_aborta_con_datos_sanos():
    from app.config.money_columns import precheck_money_columns

    base = _base_con_todas_float()

    stats = precheck_money_columns(base)

    assert len(stats) == len(MONEY_COLUMNS)
    assert all(s.fits for s in stats)
    assert not any(s.out_of_range for s in stats)


def test_precheck_aborta_si_un_valor_no_entra():
    from app.config.money_columns import precheck_money_columns

    base = _base_con_todas_float()
    objetivo = MONEY_COLUMNS_BY_TABLE["budget"][3]
    base.stats[(objetivo.table, objetivo.column)] = (
        1,
        0,
        Decimal("0.00"),
        Decimal("99999999999999999999.00"),
        1,
        0,
    )

    with pytest.raises(MoneyMigrationAbort) as exc:
        precheck_money_columns(base)

    assert "fuera de" in str(exc.value)
    assert base.executed == [] or all(
        not sql.startswith("ALTER") for sql in base.executed
    ), "el precheck no debe alterar nada"


def test_precheck_no_aborta_si_falta_una_tabla_aun_no_migrada():
    """En una base vieja la tabla puede no existir: no es motivo de aborto."""
    from app.config.money_columns import precheck_money_columns

    base = _base_con_todas_float()
    base.tables.discard("clientpayment")

    stats = precheck_money_columns(base)

    ausentes = [s for s in stats if s.actual_type == ""]
    assert len(ausentes) == 1


def test_precheck_reporta_min_max_y_nulos():
    from app.config.money_columns import precheck_money_columns

    base = _base_con_todas_float()
    objetivo = MONEY_COLUMNS_BY_TABLE["budget"][3]
    base.stats[(objetivo.table, objetivo.column)] = (
        85,
        0,
        Decimal("1366800.00"),
        Decimal("44859000.00"),
        0,
        0,
    )

    stats = precheck_money_columns(base)

    fila = next(
        s for s in stats if s.column.table == "budget" and s.column.column == "total_amount"
    )
    assert fila.rows == 85
    assert fila.minimum == Decimal("1366800.00")
    assert fila.maximum == Decimal("44859000.00")
    assert fila.nulls == 0
    assert fila.actual_type == "float"


# ---------------------------------------------------------------------------
# MigraciÃ³n
# ---------------------------------------------------------------------------


def test_la_migracion_altera_cada_columna_a_decimal_18_2(monkeypatch):
    from app.config import money_columns as modulo

    monkeypatch.setattr(modulo, "table_exists", lambda db, t: True)
    base = _base_con_todas_float()

    alteradas = modulo.migrate_money_columns_to_decimal(base)

    assert len(alteradas) == len(MONEY_COLUMNS)
    alters = [sql for sql in base.executed if sql.startswith("ALTER TABLE")]
    assert len(alters) == len(MONEY_COLUMNS)
    assert all("MODIFY COLUMN" in sql for sql in alters)
    assert any(
        "ALTER TABLE `budget` MODIFY COLUMN `total_amount` DECIMAL(18,2)" in " ".join(s.split())
        for s in alters
    )


def test_la_migracion_es_idempotente(monkeypatch):
    from app.config import money_columns as modulo

    monkeypatch.setattr(modulo, "table_exists", lambda db, t: True)
    base = _base_con_todas_float()
    for tabla, columnas in base.columns.items():
        for columna in columnas:
            columnas[columna] = "decimal(18,2)"

    alteradas = modulo.migrate_money_columns_to_decimal(base)

    assert alteradas == []
    assert not [sql for sql in base.executed if sql.startswith("ALTER")]


def test_la_migracion_no_toca_una_columna_ya_correcta(monkeypatch):
    from app.config import money_columns as modulo

    monkeypatch.setattr(modulo, "table_exists", lambda db, t: True)
    base = _base_con_todas_float()
    base.columns["budget"]["total_amount"] = "decimal(18,2)"

    alteradas = modulo.migrate_money_columns_to_decimal(base)

    assert ("budget", "total_amount") not in [(a, b) for a, b, _ in alteradas]


def test_la_migracion_es_no_op_en_otros_motores():
    from app.config.money_columns import migrate_money_columns_to_decimal

    class _NoMySQL:
        def execute_sql(self, sql, params=None):  # pragma: no cover
            raise AssertionError("no debe ejecutar SQL en un motor no MySQL")

    assert migrate_money_columns_to_decimal(_NoMySQL()) == []


def test_la_migracion_usa_una_sola_conversion_de_tipo():
    """ALTER MODIFY es una conversiÃ³n de tipo: no recalcula histÃ³ricos."""
    from app.config import money_columns as modulo

    monkey = modulo.table_exists
    modulo.table_exists = lambda db, t: True
    try:
        base = _base_con_todas_float()
        modulo.migrate_money_columns_to_decimal(base)
    finally:
        modulo.table_exists = monkey

    for sql in base.executed:
        if sql.startswith("ALTER"):
            plano = " ".join(sql.split())
            assert "UPDATE" not in plano
            assert "SET" not in plano.upper().replace("MODIFY COLUMN", "")

"""Fase 6: prueba de que DECIMAL conserva el importe que FLOAT destruye.

Dos capas:

* **Verificable hoy, sólo SELECT**: contra el MySQL configurado se comprueba la
  semántica de conversión del propio servidor. Es la demostración del defecto y
  de la solución sin escribir nada.
* **Integración real, opt-in**: ``test_decimal_conserva_el_importe_exacto`` crea
  una tabla de prueba, la migra a DECIMAL(18,2) y lee el valor de vuelta. Se
  omite salvo que se autorice una base temporal con
  ``FEMAG_MONEY_ITEST_DB``.

Importes exigidos por el encargo, más negativos porque los movimientos y los
ajustes los usan.
"""

import os
from decimal import Decimal

import pytest

from app.config.money_columns import (
    MONEY_MAX_DIGITS,
    MoneyColumn,
    unrepresentable_amounts,
)

#: Importes que deben sobrevivir exactamente a DECIMAL(18,2).
IMPORTES = [
    "0.01",
    "0.10",
    "999.99",
    "9639.00",
    "37485.00",
    "37511775.00",
    "99999999.99",
    "-0.01",
    "-999.99",
    "-37511775.00",
    # cerca del máximo definido: DECIMAL(18,2) admite 16 dígitos enteros
    "9999999999999999.99",
    "-9999999999999999.99",
]


def _servidor():
    """Conexión sólo lectura al MySQL configurado. Devuelve None si no aplica."""
    if os.getenv("FEMAG_SKIP_MONEY_MYSQL_CHECK") == "1":
        return None
    try:
        import pymysql

        from app.config.database import resolve_mysql_host_ipv4
        from app.services.monetary_audit_readonly import resolve_audit_database

        os.environ.setdefault("FEMAG_AUTO_MIGRATE_SCHEMA", "0")
        from app.config.settings import resolve_effective_connection_settings

        resolve_effective_connection_settings()
        target = resolve_audit_database()
        if target.engine != "mysql":
            return None
        return pymysql.connect(
            host=resolve_mysql_host_ipv4(target.host),
            port=target.port,
            user=target.user,
            password=target.password,
            database=target.database,
            charset="utf8mb4",
            autocommit=True,
        ), target
    except Exception:
        return None


@pytest.fixture(scope="module")
def servidor():
    resultado = _servidor()
    if resultado is None:
        pytest.skip("MySQL no disponible para la comprobación de semántica")
    conexion, _target = resultado
    yield conexion
    conexion.close()


# ---------------------------------------------------------------------------
# Capa 1: semántica del servidor, sólo SELECT, verificable hoy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("importe", IMPORTES)
def test_decimal_conserva_cada_importe_exacto(servidor, importe):
    cur = servidor.cursor()
    cur.execute("SELECT CAST(%s AS DECIMAL(18,2))", (float(importe),))

    assert cur.fetchone()[0] == Decimal(importe)


def test_float_destruye_el_importe_del_incidente(servidor):
    """El defecto, documentado como regresión: FLOAT no puede con este importe."""
    cur = servidor.cursor()
    cur.execute("SELECT CAST(%s AS FLOAT)", (37511775.00,))
    como_float = cur.fetchone()[0]
    cur.execute("SELECT CAST(%s AS DECIMAL(18,2))", (37511775.00,))
    como_decimal = cur.fetchone()[0]

    assert como_decimal == Decimal("37511775.00")
    assert como_float != Decimal("37511775.00")
    assert como_float == 37511800.0


def test_el_importe_del_incidente_ya_pasa_el_guard_de_reparacion(servidor):
    """Con DECIMAL el guard de representabilidad dejaría pasar la reparación."""
    cur = servidor.cursor()

    def _probe(valor):
        cur.execute("SELECT CAST(%s AS DECIMAL(18,2))", (valor,))
        return cur.fetchone()[0]

    fallos = unrepresentable_amounts(
        {"budget.total_amount": 37511775.00,
         "budget.net_amount": 37511775.00,
         "clientaccountmovement.total_amount": 37511775.00},
        probe=_probe,
    )

    assert fallos == []


def test_decimal_tiene_margen_sobre_el_maximo_de_produccion(servidor):
    cur = servidor.cursor()
    cur.execute("SELECT CAST(%s AS DECIMAL(18,2))", (2910410000.00,))
    maximo_produccion = cur.fetchone()[0]
    objetivo = MoneyColumn("budget", "total_amount")

    assert maximo_produccion == Decimal("2910410000.00")
    assert objetivo.max_value > abs(maximo_produccion)


def test_negativos_se_conservan_con_signo(servidor):
    cur = servidor.cursor()
    for importe in ("-0.01", "-37511775.00", "-9999999999999999.99"):
        cur.execute("SELECT CAST(%s AS DECIMAL(18,2))", (float(importe),))
        assert cur.fetchone()[0] == Decimal(importe)


# ---------------------------------------------------------------------------
# Capa 2: integración real con migración, opt-in
# ---------------------------------------------------------------------------


def _base_de_integracion():
    nombre = os.getenv("FEMAG_MONEY_ITEST_DB")
    if not nombre:
        pytest.skip(
            "Requiere autorización: definir FEMAG_MONEY_ITEST_DB con una base "
            "temporal descartable. Nunca apuntar a femag_desktop."
        )
    import pymysql

    from app.config.database import resolve_mysql_host_ipv4
    from app.services.monetary_audit_readonly import resolve_audit_database

    target = resolve_audit_database()
    conexion = pymysql.connect(
        host=resolve_mysql_host_ipv4(target.host),
        port=target.port,
        user=target.user,
        password=target.password,
        database=nombre,
        charset="utf8mb4",
        autocommit=True,
    )
    return conexion


@pytest.fixture()
def base_temporal():
    conexion = _base_de_integracion()
    cur = conexion.cursor()
    cur.execute("DROP TABLE IF EXISTS femag_money_itest")
    cur.execute(
        "CREATE TABLE femag_money_itest ("
        "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
        f"total_amount {MoneyColumn('x', 'y').decimal_type.replace('DECIMAL', 'FLOAT')} NOT NULL)"
    )
    yield conexion
    cur.execute("DROP TABLE IF EXISTS femag_money_itest")
    conexion.close()


def test_el_alter_convierte_float_a_decimal_sin_tocar_el_valor(base_temporal):
    """FLOAT -> DECIMAL es conversión de tipo: conserva lo almacenado."""
    cur = base_temporal.cursor()

    for importe in ("37511800.00", "38619.80", "-95582.60"):
        cur.execute(
            "INSERT INTO femag_money_itest (total_amount) VALUES (%s)",
            (float(importe),),
        )
    cur.execute("SELECT total_amount FROM femag_money_itest ORDER BY id")
    antes = [fila[0] for fila in cur.fetchall()]

    cur.execute(
        f"ALTER TABLE femag_money_itest MODIFY COLUMN total_amount "
        f"DECIMAL({MONEY_MAX_DIGITS},2) NOT NULL"
    )

    cur.execute("SELECT total_amount FROM femag_money_itest ORDER BY id")
    despues = [Decimal(str(fila[0])) for fila in cur.fetchall()]

    assert antes == [37511800.0, 38619.8, -95582.6]
    assert despues == [
        Decimal("37511800.00"),
        Decimal("38619.80"),
        Decimal("-95582.60"),
    ]


def test_tras_la_migracion_el_importe_correcto_sobrevive(base_temporal):
    """Ésta es la prueba que exige el encargo, sobre una base ya migrada."""
    cur = base_temporal.cursor()
    cur.execute(
        f"ALTER TABLE femag_money_itest MODIFY COLUMN total_amount "
        f"DECIMAL({MONEY_MAX_DIGITS},2) NOT NULL"
    )

    for importe in IMPORTES:
        cur.execute(
            "INSERT INTO femag_money_itest (total_amount) VALUES (%s)",
            (float(importe),),
        )

    cur.execute("SELECT total_amount FROM femag_money_itest ORDER BY id")
    leidos = [Decimal(str(fila[0])) for fila in cur.fetchall()]

    assert leidos == [Decimal(valor) for valor in IMPORTES]
    assert Decimal("37511775.00") in leidos
    assert 37511800.0 not in leidos


def test_el_guard_de_reparacion_pasa_tras_la_migracion(base_temporal):
    """Con la columna ya DECIMAL, la herramienta de reparación no bloquea."""
    from app.config.money_columns import (
        assert_persistable,
        plan_columns,
    )
    from scripts.repair_monetary_integrity import RepairPlan, Amounts

    cur = base_temporal.cursor()
    cur.execute(
        f"ALTER TABLE femag_money_itest MODIFY COLUMN total_amount "
        f"DECIMAL({MONEY_MAX_DIGITS},2) NOT NULL"
    )
    objetivo = Amounts.build(net="37511775", discount="0", vat="0", total="37511775")
    plan = RepairPlan(
        budget_id=73,
        budget_number=73,
        order_id=51,
        order_number=51,
        client_id=1,
        client_name="CARDOZO MAURICIO GUSTAVO",
        before_budget=Amounts.build(total="37511800"),
        after_budget=objetivo,
        movement_id=441,
        movement_type="load_order_documental",
        movement_source_ref="Budget:73",
        movement_reference="PRES-000073",
        before_movement=Amounts.build(total="37511800"),
        after_movement=objetivo,
    )

    columnas = plan_columns(plan)
    assert_persistable(
        {"femag_money_itest.total_amount": columnas["budget.total_amount"]},
        database=_Adaptador(base_temporal),
    )


class _Adaptador:
    """Expone la conexión pymysql con la interfaz que espera assert_persistable."""

    def __init__(self, conexion):
        self._cur = conexion.cursor()

    def execute_sql(self, sql, params=None):
        self._cur.execute(sql, params)
        return self._cur

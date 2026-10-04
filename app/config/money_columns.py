"""Registro declarativo de las columnas MONETARIAS de FEMAG y su migración a DECIMAL.

Por qué existe
--------------

El esquema MySQL real declara las columnas de dinero como ``FLOAT``, que en
MySQL es de **una sola precisión** (4 bytes, ~7 dígitos significativos). Por
encima de ``2^25 = 33.554.432`` los enteros no son representables de forma
exacta. Demostrado contra el servidor:

    SELECT CAST(37511775.00 AS FLOAT)     ->  37511800.0     (importe perdido)
    SELECT CAST(37511775.00 AS DECIMAL(18,2)) ->  37511775.00 (exacto)

Por eso el importe correcto del PRES-000073 no podía persistirse, y por eso la
postcondición de la reparación leía el valor viejo. La docstring de
``app/services/money.py`` afirma "MySQL DOUBLE", pero el esquema nunca fue
DOUBLE: es FLOAT.

Qué migra y qué no
------------------

Migramos **todo importe de dinero**. NO migramos cantidades, porcentajes,
pesos físicos ni ratios, aunque hoy estén en FLOAT: no son dinero y su
semántica de coma flotante es legítima.

La migración es un ``ALTER TABLE ... MODIFY COLUMN`` a ``DECIMAL(18,2)``, que
MySQL resuelve como *conversión de tipo*: conserva el valor almacenado y lo
redondea a 2 decimales. **No recupera precisión histórica ya perdida**:
``37511800`` sigue siendo ``37511800`` después de migrar, que es lo correcto.
Los importes históricos se reparan después, caso por caso, con la herramienta
de reparación.

Los costos unitarios y el historial de costos ya son ``DECIMAL(14,4)`` porque el
negocio usa precisión sub-centavo ahí. No se tocan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from peewee import DecimalField, FloatField, MySQLDatabase

from app.services.money import quantize_money

#: Escala de la política monetaria de ``app.services.money``: 2 decimales.
MONEY_DECIMAL_PLACES = 2

#: Dígitos enteros holgados. El máximo absoluto observado en producción es
#: 2.910.410.000,00 (10 dígitos), así que 16 deja un margen de ~3.400.000x.
MONEY_MAX_DIGITS = 18

DEFAULT_MONEY_SPEC = (MONEY_MAX_DIGITS, MONEY_DECIMAL_PLACES)

#: Tipos declarados en MySQL que pierden precisión entera por encima de 2^25.
#: ``float`` es simple (4 bytes); ``double`` sigue siendo coma flotante binaria y
#: no garantiza escala fija, así que tampoco es el contrato que buscamos.
MYSQL_SINGLE_PRECISION_TYPES = frozenset({"float"})

#: Costo unitario e historial de costos: el negocio usa precisión sub-centavo,
#: por eso ya son DECIMAL(14,4) y esta migración no los toca.
COST_SPEC = (14, 4)


@dataclass(frozen=True)
class MoneyColumn:
    """Una columna monetaria y la precisión con la que debe quedar."""

    table: str
    column: str
    max_digits: int = MONEY_MAX_DIGITS
    decimal_places: int = MONEY_DECIMAL_PLACES
    purpose: str = ""

    @property
    def decimal_type(self) -> str:
        return f"DECIMAL({self.max_digits},{self.decimal_places})"

    @property
    def max_value(self) -> Decimal:
        """Mayor valor absoluto representable, para la comprobación previa."""
        enteros = self.max_digits - self.decimal_places
        return Decimal(10) ** enteros - Decimal(1) / (Decimal(10) ** self.decimal_places)


def _spec(entries, spec=DEFAULT_MONEY_SPEC, purpose=""):
    return tuple(
        MoneyColumn(
            table=table,
            column=column,
            max_digits=spec[0],
            decimal_places=spec[1],
            purpose=purpose,
        )
        for table, column in entries
    )


#: Todas las columnas de dinero que hoy están en FLOAT y deben pasar a DECIMAL.
#: Inventario tomado de ``information_schema`` y de los modelos Peewee.
MONEY_COLUMNS: tuple[MoneyColumn, ...] = (
    # --- cabecera de presupuesto -----------------------------------------
    *_spec(
        [
            ("budget", "net_amount"),
            ("budget", "discount_amount"),
            ("budget", "vat_amount"),
            ("budget", "total_amount"),
        ],
        purpose="cabecera de presupuesto",
    ),
    # --- renglones de presupuesto ----------------------------------------
    *_spec(
        [
            ("budgetitem", "unit_price"),
            ("budgetitem", "net_subtotal"),
            ("budgetitem", "discount_amount"),
            ("budgetitem", "net_taxable"),
            ("budgetitem", "vat_amount"),
            ("budgetitem", "total"),
        ],
        purpose="renglón de presupuesto",
    ),
    # --- órdenes de carga --------------------------------------------------
    *_spec(
        [
            ("loadorderproduct", "precio_neto_unitario"),
            ("loadorderproduct", "neto_subtotal"),
            ("loadorderproduct", "descuento_importe"),
            ("loadorderproduct", "neto_gravado"),
            ("loadorderproduct", "iva_importe"),
            ("loadorderproduct", "total"),
        ],
        purpose="renglón de orden de carga",
    ),
    *_spec(
        [
            ("loadorderreturnline", "unit_price"),
            ("loadorderreturnline", "credit_amount"),
        ],
        purpose="devolución de mercadería",
    ),
    # --- cuenta corriente --------------------------------------------------
    *_spec(
        [
            ("clientaccountmovement", "amount"),
            ("clientaccountmovement", "net_amount"),
            ("clientaccountmovement", "discount_amount"),
            ("clientaccountmovement", "vat_amount"),
            ("clientaccountmovement", "total_amount"),
        ],
        purpose="movimiento de cuenta corriente",
    ),
    # --- pagos --------------------------------------------------------------
    *_spec(
        [("clientpayment", "amount")],
        purpose="recibo de pago",
    ),
    *_spec(
        [("clientpaymentdetail", "amount")],
        purpose="medio de pago del recibo",
    ),
    # --- listas de precios --------------------------------------------------
    *_spec(
        [
            ("product", "precio_neto_base"),
            ("product", "precio_lista_1"),
            ("product", "precio_lista_2"),
            ("product", "precio_lista_3"),
            ("product", "precio_lista_4"),
        ],
        purpose="precio de producto",
    ),
)

MONEY_COLUMNS_BY_TABLE: dict[str, tuple[MoneyColumn, ...]] = {}
for _money_column in MONEY_COLUMNS:
    MONEY_COLUMNS_BY_TABLE.setdefault(_money_column.table, ())
    MONEY_COLUMNS_BY_TABLE[_money_column.table] += (_money_column,)


#: Columnas que se parecen a dinero pero NO lo son, y por qué quedan afuera.
#: Documentado para que nadie las agregue después "por seguridad".
NON_MONEY_FLOAT_COLUMNS = {
    "budgetitem": {
        "quantity": "cantidad de mercadería, admite fracciones de bulto",
        "discount_percentage": "porcentaje de descuento",
        "vat_percentage": "porcentaje de IVA",
    },
    "loadorderproduct": {
        "quantity": "cantidad de mercadería",
        "descuento_porcentaje": "porcentaje de descuento",
        "iva_porcentaje": "porcentaje de IVA",
    },
    "loadorderreturnline": {"quantity": "cantidad devuelta"},
    "loadorderpallet": {"weight": "peso físico del pallet"},
    "pallettype": {"weight": "peso físico del tipo de pallet"},
    "client": {"descuento_porcentaje": "porcentaje de descuento del cliente"},
    "tipoiva": {"porcentaje": "porcentaje de IVA"},
}


def money_field(
    *,
    null: bool = False,
    default="0.00",
    max_digits: int = MONEY_MAX_DIGITS,
    decimal_places: int = MONEY_DECIMAL_PLACES,
) -> DecimalField:
    """Campo monetario DECIMAL para los modelos Peewee.

    El default es ``Decimal`` y no ``float``: un default float reintroduciría
    exactamente el problema que se está corrigiendo.
    """
    return DecimalField(
        max_digits=max_digits,
        decimal_places=decimal_places,
        null=null,
        auto_round=False,
        default=(None if null else Decimal(default).scaleb(-decimal_places)),
    )


def money_fields(max_digits: int = MONEY_MAX_DIGITS, decimal_places: int = MONEY_DECIMAL_PLACES):
    """``default=Decimal('0.00')`` para la escala elegida."""
    return Decimal(default_str(decimal_places))


def default_str(decimal_places: int) -> str:
    return "0." + ("0" * decimal_places) if decimal_places else "0"


class MoneyMigrationAbort(RuntimeError):
    """La migración o la escritura no puede continuar sin perder datos."""


def is_exact_decimal(value) -> bool:
    """``True`` si ``value`` no tiene más decimales que la escala monetaria."""
    quantized = Decimal(str(value)).quantize(Decimal(1).scaleb(-MONEY_DECIMAL_PLACES))
    return quantized == Decimal(str(value))


def unrepresentable_amounts(columns: dict[str, float], *, probe) -> list[tuple[str, float, float]]:
    """Columnas cuyo importe NO sobreviviría al tipo real de la columna.

    ``probe`` es el servidor: recibe un importe y devuelve lo que MySQL
    almacenaría de verdad (``SELECT CAST(%s AS FLOAT)``). La comparación se
    hace sobre el importe cuantizado a moneda, nunca sobre el float crudo.

    Esto NO relaja ninguna verificación posterior: sólo evita escribir un valor
    que la base no puede guardar y perderlo en silencio.
    """
    fallos = []
    for columna, valor in columns.items():
        cuantizado = float(quantize_money(valor))
        persistido = float(quantize_money(probe(cuantizado)))
        if persistido != cuantizado:
            fallos.append((columna, cuantizado, persistido))
    return fallos


def mysql_float_probe(database):
    """Pregunta al servidor qué guardaría realmente en una columna FLOAT."""

    def _probe(valor: float) -> float:
        fila = database.execute_sql("SELECT CAST(%s AS FLOAT)", (valor,)).fetchone()
        return fila[0] if fila else valor

    return _probe


def assert_persistable(columns: dict[str, float], *, database) -> None:
    """Aborta si algún importe destino no cabe exactamente en su columna.

    Sólo lectura (``information_schema`` + ``CAST``) y se usa ANTES de abrir
    cualquier transacción de escritura.
    """
    tables_and_columns: dict[str, list[str]] = {}
    for columna in columns:
        tabla, _, nombre = columna.partition(".")
        tables_and_columns.setdefault(tabla, []).append(nombre)
    tipos = money_column_types(database, tables_and_columns)

    single_precision = {
        columna: valor
        for columna, valor in columns.items()
        if tipos.get(columna) in MYSQL_SINGLE_PRECISION_TYPES
    }
    if not single_precision:
        return

    fallos = unrepresentable_amounts(single_precision, probe=mysql_float_probe(database))
    if not fallos:
        return
    detalle = "; ".join(
        f"{columna}: se intentaría guardar {valor:,.2f} "
        f"y la base guardaría {persistido:,.2f}"
        for columna, valor, persistido in fallos
    )
    raise MoneyMigrationAbort(
        "El importe destino no es representable en el tipo real de la columna "
        f"({detalle}). Las columnas monetarias están declaradas 'float' en MySQL, "
        "que es de una sola precisión (~7 dígitos significativos): por encima de "
        "2^25 = 33.554.432 los enteros no son exactos, así que la escritura se "
        "pierde en silencio y la verificación posterior vuelve a leer el valor "
        "viejo. Pasar las columnas a DECIMAL requiere la migración "
        "app/config/money_columns.py, fuera del alcance de una reparación "
        "puntual. No se modificó nada."
    )


def table_exists(database, table: str) -> bool:
    row = database.execute_sql(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    ).fetchone()
    return bool(row and row[0])


def money_column_types(database, tables_and_columns) -> dict[str, str]:
    """Tipo declarado de cada columna monetaria. Sólo SELECT.

    Sólo MySQL tiene ``information_schema`` y una restricción de precisión
    declarada. En SQLite las columnas ``REAL`` son de 8 bytes y no imponen este
    límite, así que se devuelve vacío y la puerta no aplica.
    """
    if not isinstance(database, MySQLDatabase):
        return {}
    tipos: dict[str, str] = {}
    for tabla, columnas in tables_and_columns.items():
        # pymysql usa marcadores de formato %s, no el qmark de sqlite3.
        filas = database.execute_sql(
            "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (tabla,),
        ).fetchall()
        por_nombre = {str(f[0]).lower(): str(f[1]).lower() for f in filas}
        for columna in columnas:
            tipo = por_nombre.get(columna.lower())
            if tipo:
                tipos[f"{tabla}.{columna}"] = tipo
    return tipos


def current_column_type(database, table: str, column: str) -> str | None:
    row = database.execute_sql(
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    ).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0]).lower()


_NEEDS_DECIMAL = re.compile(r"^(float|double|real)\b|^(decimal|numeric)\((\d+)\s*,\s*(\d+)\)$")


def needs_decimal_migration(actual_type: str | None, target: MoneyColumn) -> bool:
    """``True`` si la columna actual no es el DECIMAL exacto que queremos.

    ``DOUBLE`` también necesita migración: 53 bits de mantissa no son el mismo
    contrato que un DECIMAL con escala fija, y elFloat simple ya demostró que
    no alcanza.
    """
    if actual_type is None:
        return False
    actual = actual_type.strip().lower()
    if actual.startswith("decimal") or actual.startswith("numeric"):
        match = re.search(r"\((\d+)\s*,\s*(\d+)\)", actual)
        if not match:
            return True
        return (int(match.group(1)), int(match.group(2))) != (
            target.max_digits,
            target.decimal_places,
        )
    return True


@dataclass(frozen=True)
class ColumnStats:
    """Lo que el diagnóstico previo necesita saber de una columna."""

    column: MoneyColumn
    actual_type: str
    rows: int
    nulls: int
    minimum: Decimal | None
    maximum: Decimal | None
    out_of_range: int
    off_scale: int

    @property
    def fits(self) -> bool:
        return self.out_of_range == 0


def column_stats(database, column: MoneyColumn) -> ColumnStats:
    """MIN/MAX/NULL/valores fuera de rango. Sólo SELECT."""
    if not table_exists(database, column.table):
        return ColumnStats(column, "", 0, 0, None, None, 0, 0)

    table = _escape(column.table)
    name = _escape(column.column)
    row = database.execute_sql(
        f"SELECT COUNT(*), "
        f"SUM(CASE WHEN `{name}` IS NULL THEN 1 ELSE 0 END), "
        f"MIN(`{name}`), MAX(`{name}`), "
        f"SUM(CASE WHEN `{name}` IS NOT NULL AND ABS(`{name}`) > %s THEN 1 ELSE 0 END), "
        f"SUM(CASE WHEN `{name}` IS NOT NULL AND `{name}` <> ROUND(`{name}`, {column.decimal_places}) THEN 1 ELSE 0 END) "
        f"FROM `{table}`",
        (column.max_value,),
    ).fetchone()
    filas, nulos, minimo, maximo, fuera, escala = row
    return ColumnStats(
        column=column,
        actual_type=current_column_type(database, column.table, column.column) or "",
        rows=int(filas or 0),
        nulls=int(nulos or 0),
        minimum=Decimal(str(minimo)) if minimo is not None else None,
        maximum=Decimal(str(maximo)) if maximo is not None else None,
        out_of_range=int(fuera or 0),
        off_scale=int(escala or 0),
    )


def precheck_money_columns(database) -> list[ColumnStats]:
    """Diagnóstico previo. Lanza ``MoneyMigrationAbort`` si algún valor no entra."""
    stats = [column_stats(database, column) for column in MONEY_COLUMNS]
    fuera = [s for s in stats if not s.fits]
    if fuera:
        detalle = "; ".join(
            f"{s.column.table}.{s.column.column}: {s.out_of_range} valor(es) fuera de "
            f"{s.column.decimal_type}"
            for s in fuera
        )
        raise MoneyMigrationAbort(
            "La migración se aborta: hay valores que no entran en el DECIMAL destino. "
            f"{detalle}. No se modificó ninguna columna."
        )
    return stats


def migrate_money_columns_to_decimal(database) -> list[tuple[str, str, str]]:
    """ALTER TABLE ... MODIFY COLUMN a DECIMAL exacto, sólo en MySQL.

    Idempotente: una columna ya en el DECIMAL destino no se toca. Devuelve las
    columnas realmente alteradas para poder informarlas.
    """
    if not isinstance(database, MySQLDatabase):
        return []

    alteradas: list[tuple[str, str, str]] = []
    for column in MONEY_COLUMNS:
        if not table_exists(database, column.table):
            continue
        actual = current_column_type(database, column.table, column.column)
        if actual is None:
            continue
        if not needs_decimal_migration(actual, column):
            continue
        database.execute_sql(
            f"ALTER TABLE `{_escape(column.table)}` "
            f"MODIFY COLUMN `{_escape(column.column)}` {column.decimal_type} NOT NULL"
        )
        alteradas.append((column.table, column.column, f"{actual} -> {column.decimal_type}"))
    return alteradas


def _escape(value: str) -> str:
    return value.replace("`", "``")

"""Lectura de la auditoría de integridad monetaria con garantías READ-ONLY.

Este módulo es el único punto del auditor que toca la base. Todo lo que hace
es ``SELECT``: no importa servicios mutadores, no llama ``ensure_*``, no crea,
no actualiza, no borra y no genera movimientos.

Defensa técnica, en capas
-------------------------

1. **No se usa el conector de la aplicación.** ``FemagMySQLDatabase.connect()``
   ejecuta ``ensure_runtime_schema()`` y siembra los medios de pago: conectar
   con él ya escribe. El auditor construye un ``MySQLDatabase`` pelado, así que
   esa ruta nunca se dispara.
2. **Guard de SQL (portable).** Todas las consultas de peewee pasan por
   ``Database.execute_sql``. Ese único punto se intercepta y se rechaza
   cualquier sentencia cuyo verbo no sea de lectura. Es la protección que no
   depende del motor.
3. **Motor en modo solo lectura.** En SQLite el archivo se abre con
   ``file:<ruta>?mode=ro``: el propio motor rechaza la escritura aunque se
   esquive el guard. En MySQL se intenta ``SET SESSION TRANSACTION READ ONLY``
   y, si el servidor no lo soporta, ``START TRANSACTION READ ONLY``.
4. **Verificación por test.** ``tests/test_monetary_audit_readonly.py`` compara
   cantidad y hash de filas antes y después de auditar.

Las capas 1, 2 y 3 sonoras se reportan en ``ReadOnlyHandle.protections`` para
que el informe diga exactamente qué protección está activa y no prometa nada
que no se haya aplicado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from peewee import Database, DatabaseError, MySQLDatabase, SqliteDatabase

from app.config.database import bind_database, database_proxy
from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget, BudgetItem
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Client
from app.services.money import ZERO_MONEY, compute_line_amounts, money_sum, quantize_money
from app.services.monetary_audit import (
    Amounts,
    BudgetAudit,
    LedgerBucket,
    LedgerCandidate,
    classify_budget_integrity,
    classify_ledger,
    classify_order_comparison,
)

SQL_GUARD_PROTECTION = "sql_allowlist_guard"
SQLITE_PROTECTION = "sqlite_audit_readonly"
MYSQL_PROTECTION = "mysql_read_only_transaction"

#: Sentencias que el auditor emite para abrir la transacción de solo lectura.
MYSQL_READ_ONLY_STATEMENTS = (
    "SET SESSION TRANSACTION READ ONLY",
    "START TRANSACTION READ ONLY",
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_LEADING_VERB = re.compile(r"^([A-Za-z_]+)")

#: Únicos verbos aceptados por el guard.
ALLOWED_SQL_VERBS = frozenset(
    {
        "SELECT",
        "WITH",
        "SHOW",
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
        "PRAGMA",
        "BEGIN",
        "START",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "RELEASE",
        "END",
    }
)

#: ``SET`` solo se admite para abrir la transacción de solo lectura. Cualquier
#: otro ``SET`` (GLOBAL, SESSION de variables de sesión, autocommit) se rechaza.
ALLOWED_SET_PREFIXES = ("SESSION TRANSACTION",)


class ReadOnlyViolation(RuntimeError):
    """Se intentó una escritura sobre la conexión del auditor."""


class EffectiveConfigurationError(RuntimeError):
    """La configuración efectiva de FEMAG no se puede usar para auditar.

    Se lanza, entre otros casos, cuando la configuración segura del puesto está
    activa pero la resolución no termina en MySQL. El auditor nunca degrada a
    SQLite para "seguir adelante": auditar otra base que la que usa la aplicación
    produciría un informe falso.
    """


def assert_read_only_sql(sql: str) -> str:
    """Valida que ``sql`` sea una sentencia de lectura. Devuelve el texto limpio.

    Es la lista blanca del guard: lo que no está explícitamente permitido se
    rechaza. Los valores de una consulta viajan como parámetros, no dentro del
    texto SQL, así que no hay literales que puedan falsear el análisis.
    """
    cleaned = _BLOCK_COMMENT.sub(" ", sql or "")
    cleaned = _LINE_COMMENT.sub(" ", cleaned).strip()
    match = _LEADING_VERB.match(cleaned)
    verb = (match.group(1).upper() if match else "")
    if verb in ALLOWED_SQL_VERBS:
        return cleaned
    if verb == "SET":
        upper = cleaned.upper()
        if any(upper.startswith(f"SET {prefix}") for prefix in ALLOWED_SET_PREFIXES):
            return cleaned
    raise ReadOnlyViolation(
        "La auditoría monetaria es READ-ONLY y rechazó una sentencia de escritura: "
        f"{cleaned[:120]!r}"
    )


class _ReadOnlySqlGuard:
    """Intercepta el único punto por el que peewee ejecuta SQL."""

    def execute_sql(self, sql, params=None):
        assert_read_only_sql(sql)
        return super().execute_sql(sql, params)


class ReadOnlySqliteDatabase(_ReadOnlySqlGuard, SqliteDatabase):
    """SQLite abierto en modo solo lectura a nivel de motor.

    ``mode=ro`` hace que el propio SQLite rechace ``INSERT``/``UPDATE``/
    ``DELETE`` aunque se salte el guard de SQL.
    """

    def __init__(self, path):
        super().__init__(f"file:{Path(path)}?mode=ro", pragmas={"foreign_keys": 1}, uri=True)


class ReadOnlyMySQLDatabase(_ReadOnlySqlGuard, MySQLDatabase):
    """MySQL pelado con transacción de solo lectura si el motor la soporta.

    No hereda de ``FemagMySQLDatabase`` justamente para no disparar
    ``ensure_runtime_schema()`` ni la siembra de medios de pago al conectar.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read_only_statements: tuple[str, ...] = ()

    def connect(self, *args, **kwargs):
        result = super().connect(*args, **kwargs)
        if result and not self.read_only_statements:
            self.read_only_statements = _apply_mysql_read_only(self)
        return result


def _apply_mysql_read_only(database: MySQLDatabase) -> tuple[str, ...]:
    """Abre una transacción de solo lectura con la primera variante soportada.

    Devuelve exactamente la sentencia aplicada. Si el motor no soporta ninguna,
    devuelve vacío y el informe lo declara: la protección que queda activa es el
    guard de SQL, no una garantía del servidor.
    """
    for statement in MYSQL_READ_ONLY_STATEMENTS:
        try:
            database.execute_sql(statement)
        except DatabaseError:
            continue
        return (statement,)
    return ()


@dataclass
class ReadOnlyHandle:
    """Conexión de auditoría y las protecciones realmente aplicadas."""

    database: Database
    protections: tuple[str, ...]

    def close(self) -> None:
        try:
            self.database.close()
        except Exception:  # pragma: no cover - cierre defensivo
            pass


def open_readonly_sqlite(path) -> ReadOnlyHandle:
    """Abre una base SQLite en modo solo lectura y la enlaza al proxy de modelos.

    Enlazar el proxy reemplaza la base de la sesión actual: el auditor es una
    herramienta de línea de comandos, no un servicio para usar dentro de la
    aplicación ya abierta.
    """
    database = ReadOnlySqliteDatabase(path)
    bind_database(database)
    database.connect(reuse_if_open=True)
    return ReadOnlyHandle(
        database=database,
        protections=(SQL_GUARD_PROTECTION, SQLITE_PROTECTION),
    )


def open_readonly_mysql(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> ReadOnlyHandle:
    """Abre MySQL en solo lectura y la enlaza al proxy de modelos."""
    engine = ReadOnlyMySQLDatabase(
        database,
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
    )
    bind_database(engine)
    engine.connect(reuse_if_open=True)
    protections = [SQL_GUARD_PROTECTION]
    if engine.read_only_statements:
        protections.append(MYSQL_PROTECTION)
    return ReadOnlyHandle(database=engine, protections=tuple(protections))


@dataclass(frozen=True)
class AuditDatabaseTarget:
    """Conexión que el auditor va a leer, ya resuelta desde la config de FEMAG.

    Es el resultado de :func:`resolve_audit_database`: la resolución es una
    etapa separada de la apertura para poder informar a qué base se audita sin
    haber conectado todavía.
    """

    engine: str
    sqlite_path: Path | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    user: str | None = None
    password: str = ""
    secure_config: bool = False

    def __repr__(self) -> str:
        """Oculta la contraseña para que no pueda filtrarse por accidente."""
        return (
            f"AuditDatabaseTarget(engine={self.engine!r}, host={self.host!r}, "
            f"port={self.port!r}, database={self.database!r}, user={self.user!r}, "
            f"sqlite_path={str(self.sqlite_path)!r}, secure_config={self.secure_config!r}, "
            f"password=<oculta>)"
        )

    __str__ = __repr__

    def header_lines(self) -> list[str]:
        """Encabezado del informe: qué base se audita. **Nunca** la contraseña."""
        lineas = [f"Database engine: {'MySQL' if self.engine == 'mysql' else 'SQLite'}"]
        if self.engine == "mysql":
            lineas.append(f"Host: {self.host}")
            lineas.append(f"Port: {self.port}")
            lineas.append(f"Database: {self.database}")
            lineas.append(f"User: {self.user}")
        else:
            lineas.append(f"SQLite path: {self.sqlite_path}")
        lineas.append(
            f"Connection source: {'configuracion segura del puesto (DPAPI)' if self.secure_config else 'configuracion efectiva (env / .env)'}"
        )
        return lineas


def resolve_audit_database(
    *,
    demo_mode: bool = False,
    database_name: str | None = None,
    settings=None,
) -> AuditDatabaseTarget:
    """Resuelve la conexión efectiva de FEMAG. No abre nada y no escribe nada.

    Reutiliza el preámbulo de conexión del proyecto
    (``app.config.settings.resolve_effective_connection_settings``), el mismo
    que aplica ``app.main.run_ui()`` antes de leer los settings. Por eso el
    auditor conecta a la misma base que la aplicación aunque el ``.env`` del
    repositorio todavía apunte a la demo SQLite.

    Si la configuración normal de FEMAG es MySQL y no se puede resolver o
    abrir, esta función propaga el error: **no** hay fallback a SQLite.
    ``database_name`` permite apuntar a otra base del mismo servidor, que es lo
    que se usa para auditar una copia local de producción.
    """
    from app.config.settings import (
        load_settings,
        resolve_effective_connection_settings,
    )

    secure_config = resolve_effective_connection_settings(demo_mode=demo_mode)
    resolved = load_settings() if settings is None else settings

    if secure_config and resolved.db_engine != "mysql":
        raise EffectiveConfigurationError(
            "FEMAG tiene configuracion segura del puesto, que exige MySQL, pero la "
            f"configuracion efectiva resolveria {resolved.db_engine!r}. No se audita "
            "otra base para no entregar un informe falso."
        )
    if resolved.db_engine == "sqlite":
        return AuditDatabaseTarget(
            engine="sqlite",
            sqlite_path=resolved.sqlite_path,
            secure_config=False,
        )
    return AuditDatabaseTarget(
        engine="mysql",
        host=resolved.db_host,
        port=resolved.db_port,
        database=(database_name or resolved.db_name),
        user=resolved.db_user,
        password=resolved.db_password,
        secure_config=secure_config,
    )


def open_audit_database(
    *,
    demo_mode: bool = False,
    database_name: str | None = None,
    target: AuditDatabaseTarget | None = None,
) -> ReadOnlyHandle:
    """Abre la conexión resuelta en modo READ-ONLY.

    MySQL se abre con :class:`ReadOnlyMySQLDatabase`, nunca con
    ``FemagMySQLDatabase`` (cuyo ``connect()`` migra el esquema y siembra datos).
    Si MySQL no abre, el error sube: no hay degradación silenciosa a SQLite.
    """
    resolved = target or resolve_audit_database(
        demo_mode=demo_mode, database_name=database_name
    )
    if resolved.engine == "mysql":
        return open_readonly_mysql(
            host=resolved.host,
            port=resolved.port,
            user=resolved.user,
            password=resolved.password,
            database=resolved.database,
        )
    return open_readonly_sqlite(resolved.sqlite_path)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

ORIGINAL_MOVEMENT_TYPES = (
    ClientAccountMovement.TYPE_LOAD_ORDER,
    ClientAccountMovement.TYPE_BUDGET_MANUAL,
)
PAYMENT_TYPES = (ClientAccountMovement.TYPE_PAYMENT,)
PAYMENT_REVERSAL_TYPES = (ClientAccountMovement.TYPE_PAYMENT_REVERSAL,)
ADJUSTMENT_TYPES = (
    ClientAccountMovement.TYPE_MANUAL_DEBIT,
    ClientAccountMovement.TYPE_MANUAL_CREDIT,
    ClientAccountMovement.TYPE_RETURN_CREDIT,
)
ADJUSTMENT_REVERSAL_TYPES = (
    ClientAccountMovement.TYPE_MANUAL_DEBIT_REVERSAL,
    ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL,
    ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL,
)


def _is_reversal(movement: ClientAccountMovement) -> bool:
    return bool(movement.is_reversal)


def _is_original(movement: ClientAccountMovement) -> bool:
    return not _is_reversal(movement)


def _budget_reference(budget: Budget) -> str:
    return f"PRES-{budget.budget_number:06d}"


def _matches_budget(movement: ClientAccountMovement, budget: Budget) -> bool:
    """Vínculos reales entre un movimiento y el presupuesto que lo originó.

    FEMAG registra el vínculo de tres formas a lo largo del tiempo y las tres
    se respetan, igual que hace el detalle de documentos de la pantalla de
    cuenta corriente:

    1. ``budget_id`` (vínculo directo, el actual);
    2. ``source_ref = "Budget:<id>"``;
    3. ``reference = "PRES-<numero>"`` (legado).
    """
    if movement.budget_id == budget.id:
        return True
    if (movement.source_ref or "") == f"Budget:{budget.id}":
        return True
    return (movement.reference or "") == _budget_reference(budget)


def _order_row_amounts(row: LoadOrderProduct) -> Amounts:
    """Importes de un renglón de orden con la misma rutina que el presupuesto.

    Se recalcula con ``compute_line_amounts`` en lugar de leer los importes
    guardados: si el renglón quedó con importes viejos, la auditoría debe ver el
    valor que la orden representa hoy, no el que alguna vez se calculó.
    """
    amounts = compute_line_amounts(
        quantity=row.quantity,
        unit_price=row.precio_neto_unitario,
        discount_percentage=row.descuento_porcentaje,
        vat_percentage=row.iva_porcentaje,
    )
    return Amounts.build(
        net=amounts.net_subtotal,
        discount=amounts.discount_amount,
        vat=amounts.vat_amount,
        total=amounts.total,
    )


class MonetaryIntegrityAuditor:
    """Audita los presupuestos cruzando detalle, cabecera y cuenta corriente.

    Solo emite ``SELECT``. No crea presupuestos ausentes ni movimientos: si una
    orden todavía no tiene presupuesto, el auditor informa que no hay nada que
    auditar en lugar de generarlo.
    """

    def __init__(self, database: Database | None = None):
        if database is not None:
            self.database = database
        elif getattr(database_proxy, "obj", None) is not None:
            self.database = database_proxy.obj
        else:
            raise RuntimeError(
                "La auditoría necesita una conexión READ-ONLY. Usar "
                "resolve_audit_database() y open_audit_database()."
            )

    # -- carga ---------------------------------------------------------------

    def _budget_rows(
        self, *, budget_id: int | None, budget_number: int | None
    ) -> list[Budget]:
        query = Budget.select().order_by(Budget.id)
        if budget_id is not None:
            query = query.where(Budget.id == budget_id)
        if budget_number is not None:
            query = query.where(Budget.budget_number == budget_number)
        return list(query)

    def _detail_amounts(self, budget_ids: Sequence[int]) -> dict[int, Amounts]:
        if not budget_ids:
            return {}
        rows = (
            BudgetItem.select()
            .where(BudgetItem.budget.in_(list(budget_ids)))
            .order_by(BudgetItem.budget, BudgetItem.id)
        )
        grouped: dict[int, list[BudgetItem]] = {}
        for row in rows:
            grouped.setdefault(row.budget_id, []).append(row)
        return {
            budget_id: Amounts.build(
                net=money_sum(item.net_subtotal for item in items),
                discount=money_sum(item.discount_amount for item in items),
                vat=money_sum(item.vat_amount for item in items),
                total=money_sum(item.total for item in items),
            )
            for budget_id, items in grouped.items()
        }

    def _order_rows_for_client(
        self, order: LoadOrder, client_id: int
    ) -> list[LoadOrderProduct]:
        """Renglones de la orden que corresponden a un cliente.

        Replica la selección de ``BudgetService`` (destino del cliente y, como
        respaldo, renglones sin destino cuando la orden es de ese cliente) sin
        usar ese servicio, porque puede escribir.
        """
        rows = list(
            LoadOrderProduct.select()
            .join(LoadOrderDestination, on=LoadOrderProduct.destination)
            .where(
                (LoadOrderProduct.order == order.id)
                & (LoadOrderDestination.client == client_id)
            )
            .order_by(LoadOrderProduct.id)
        )
        if rows:
            return rows
        if order.client_id == client_id:
            return list(
                LoadOrderProduct.select()
                .where(
                    (LoadOrderProduct.order == order.id)
                    & (LoadOrderProduct.destination.is_null(True))
                )
                .order_by(LoadOrderProduct.id)
            )
        return []

    def _order_state(
        self,
        orders: dict[int, LoadOrder],
        client_pairs: Iterable[tuple[int, int]],
    ) -> dict[tuple[int, int], tuple[Amounts, object | None, object | None]]:
        """Totales actuales de la orden por cliente, con fechas de modificación.

        Se cubren los clientes de las órdenes **y** los clientes de los
        presupuestos: en una orden con varios destinos, un presupuesto puede
        apuntar a un cliente que no es el titular de la orden.
        """
        pairs = {
            (order.id, order.client_id)
            for order in orders.values()
            if order.client_id is not None
        }
        pairs.update(pair for pair in client_pairs if pair[1] is not None)
        state: dict[tuple[int, int], tuple[Amounts, object | None, object | None]] = {}
        for order_id, client_id in sorted(pairs):
            order = orders.get(order_id)
            if order is None:
                continue
            rows = self._order_rows_for_client(order, client_id)
            if not rows:
                continue
            total = Amounts()
            for row in rows:
                total = total + _order_row_amounts(row)
            item_updated = max(
                (row.updated_at for row in rows if row.updated_at is not None),
                default=None,
            )
            state[(order_id, client_id)] = (total, order.updated_at, item_updated)
        return state

    def _movements(
        self, client_ids: Sequence[int], order_ids: Sequence[int]
    ) -> list[ClientAccountMovement]:
        if not client_ids and not order_ids:
            return []
        conditions = []
        if client_ids:
            conditions.append(ClientAccountMovement.client.in_(list(client_ids)))
        if order_ids:
            conditions.append(ClientAccountMovement.load_order.in_(list(order_ids)))
        condition = conditions[0]
        for extra in conditions[1:]:
            condition = condition | extra
        return list(
            ClientAccountMovement.select()
            .where(condition)
            .order_by(ClientAccountMovement.id)
        )

    def _reversals_by_original(
        self, movement_ids: Sequence[int]
    ) -> dict[int, tuple[Decimal, int]]:
        if not movement_ids:
            return {}
        rows = (
            ClientAccountMovement.select()
            .where(ClientAccountMovement.reverses_id.in_(list(movement_ids)))
            .order_by(ClientAccountMovement.id)
        )
        totals: dict[int, Decimal] = {}
        counts: dict[int, int] = {}
        for row in rows:
            key = row.reverses_id
            totals[key] = quantize_money(
                totals.get(key, ZERO_MONEY) + quantize_money(row.total_amount)
            )
            counts[key] = counts.get(key, 0) + 1
        return {key: (totals[key], counts[key]) for key in totals}

    # -- auditoría -----------------------------------------------------------

    def run(
        self,
        *,
        budget_id: int | None = None,
        budget_number: int | None = None,
    ) -> list[BudgetAudit]:
        budgets = self._budget_rows(budget_id=budget_id, budget_number=budget_number)
        if not budgets:
            return []

        client_ids = sorted({b.client_id for b in budgets if b.client_id is not None})
        order_ids = sorted({b.load_order_id for b in budgets if b.load_order_id is not None})
        clients = (
            {row.id: row for row in Client.select().where(Client.id.in_(client_ids))}
            if client_ids
            else {}
        )
        orders = (
            {row.id: row for row in LoadOrder.select().where(LoadOrder.id.in_(order_ids))}
            if order_ids
            else {}
        )

        detail_by_budget = self._detail_amounts([b.id for b in budgets])
        budget_pairs = {
            (b.load_order_id, b.client_id)
            for b in budgets
            if b.load_order_id is not None and b.client_id is not None
        }
        order_state = self._order_state(orders, budget_pairs)

        movements = self._movements(client_ids, order_ids)
        reversals = self._reversals_by_original([m.id for m in movements])

        audits = []
        for budget in budgets:
            audits.append(
                self._audit_budget(
                    budget=budget,
                    client=clients.get(budget.client_id),
                    order=orders.get(budget.load_order_id) if budget.load_order_id else None,
                    detail=detail_by_budget.get(budget.id, Amounts()),
                    order_state=order_state,
                    movements=movements,
                    reversals=reversals,
                )
            )
        return audits

    def _audit_budget(
        self,
        *,
        budget: Budget,
        client: Client | None,
        order: LoadOrder | None,
        detail: Amounts,
        order_state: dict,
        movements: Iterable[ClientAccountMovement],
        reversals: dict,
    ) -> BudgetAudit:
        header = Amounts.build(
            net=budget.net_amount,
            discount=budget.discount_amount,
            vat=budget.vat_amount,
            total=budget.total_amount,
        )
        integrity = classify_budget_integrity(header=header, detail=detail)

        state = order_state.get((budget.load_order_id, budget.client_id)) if order else None
        order_amounts = state[0] if state is not None else None
        order_comparison = classify_order_comparison(
            budget_detail_total=detail.total,
            order_amounts=order_amounts,
            order_updated_at=state[1] if state else None,
            item_updated_at=state[2] if state else None,
            budget_created_at=budget.created_at,
        )

        candidates = []
        payments = LedgerBucket()
        payment_reversals = LedgerBucket()
        adjustments = LedgerBucket()
        adjustment_reversals = LedgerBucket()

        for movement in movements:
            if (
                _is_original(movement)
                and movement.movement_type in ORIGINAL_MOVEMENT_TYPES
                and _matches_budget(movement, budget)
            ):
                reversal_amount, _count = reversals.get(movement.id, (ZERO_MONEY, 0))
                candidates.append(
                    LedgerCandidate(
                        movement_id=movement.id,
                        movement_type=movement.movement_type,
                        net=movement.net_amount,
                        discount=movement.discount_amount,
                        vat=movement.vat_amount,
                        total=movement.total_amount,
                        reversal_total=reversal_amount,
                        movement_date=movement.movement_date,
                        source_ref=movement.source_ref,
                        reference=movement.reference,
                    )
                )
                continue

            # Pagos, reversiones de pago, ajustes y notas de crédito son
            # contexto del cliente: se informan pero NUNCA se comparan contra
            # el presupuesto ni se suman al débito original.
            if budget.client_id is None or movement.client_id != budget.client_id:
                continue
            amount = abs(quantize_money(movement.total_amount))
            bucket = LedgerBucket(amount=amount, count=1)
            if movement.movement_type in PAYMENT_TYPES:
                payments = payments + bucket
            elif movement.movement_type in PAYMENT_REVERSAL_TYPES:
                payment_reversals = payment_reversals + bucket
            elif movement.movement_type in ADJUSTMENT_TYPES:
                adjustments = adjustments + bucket
            elif movement.movement_type in ADJUSTMENT_REVERSAL_TYPES:
                adjustment_reversals = adjustment_reversals + bucket

        ledger = classify_ledger(
            detail_total=detail.total,
            header_total=header.total,
            candidates=candidates,
            cancelled=_is_cancelled(budget, order),
            payments=payments,
            payment_reversals=payment_reversals,
            adjustments=adjustments,
            adjustment_reversals=adjustment_reversals,
        )

        return BudgetAudit(
            budget_id=budget.id,
            budget_number=budget.budget_number,
            client_id=budget.client_id,
            client_name=client.name if client is not None else None,
            order_id=budget.load_order_id,
            order_number=order.order_number if order is not None else None,
            budget_date=budget.issue_date,
            budget_status=budget.status,
            budget_origin=budget.origin,
            integrity=integrity,
            order=order_comparison,
            ledger=ledger,
        )


def _is_cancelled(budget: Budget, order: LoadOrder | None) -> bool:
    """Operación anulada: presupuesto manual anulado u orden anulada."""
    if budget.status == Budget.STATUS_ANNULLED:
        return True
    return order is not None and order.status == LoadOrder.STATUS_ANNULLED

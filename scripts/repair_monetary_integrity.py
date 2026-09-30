"""Reparación CONTROLADA y de a uno de inconsistencias monetarias históricas.

Esta herramienta es **separada** del auditor READ-ONLY y complementaria:

* ``scripts/audit_monetary_integrity.py`` sólo informa. No escribe.
* ``scripts/repair_monetary_integrity.py`` escribe, y sólo lo que el operador
  le pide explícitamente.

Política
--------

1. **Un presupuesto por ejecución.** Se exige exactamente un identificador
   explícito (``--budget <id>`` o ``--budget-number <número>``). No existe
   ``--all``, ni lote, ni comodín, ni reparación por defecto de "lo que haya".
2. **Siempre DRY-RUN.** ``--apply`` es obligatorio para escribir.
3. **Reusa la clasificación del auditor.** Antes de tocar nada se vuelve a
   auditar con :class:`MonetaryIntegrityAuditor` y se exigen cuatro condiciones:

   a. ``budget_integrity == BUDGET_HEADER_MISMATCH``;
   b. ``ledger_integrity == LEDGER_MATCH_HEADER`` (el débito original coincide
      con la cabecera, o sea que la deuda registrada arrastra el error);
   c. el detalle coincide EXACTAMENTE con el total actual de la orden, que es la
      fuente de verdad confirmada para este caso;
   d. hay EXACTAMENTE un movimiento original. Cero o varios ⇒ aborto.

   Si alguna falla, aborta sin escribir. No infiere ni adivina.
4. **No toca** ``ORDER_BUDGET_DRIFT``: una orden editada después del snapshot no
   es un defecto de la cabecera ni de la deuda.
5. **Una sola transacción.** Actualiza únicamente campos monetarios de
   ``Budget`` y del movimiento original identificado, verifica las invariantes
   ANTES del commit y registra el ``AuditLog`` dentro de esa misma transacción.
   Si algo falla, se revierte todo, incluida la auditoría.
6. **Idempotente.** Un presupuesto ya consistente no se modifica, no genera un
   segundo ajuste y no duplica el ``AuditLog``.

Fuente de verdad
----------------

Para este tipo de reparación la fuente correcta y ya confirmada es el detalle
persistido del presupuesto, que a su vez coincide con el estado actual de la
orden de carga. Por eso ``AFTER`` es siempre la suma de ``BudgetItem`` y nunca
un importe calculado a mano.

Conexión
--------

La resolución de configuración es la misma del auditor
(:func:`app.services.monetary_audit_readonly.resolve_audit_database`), así que
la herramienta apunta a la base que usa FEMAG y no a la demo. La diferencia
deliberada es el motor: aquí se abre una conexión **escribible** con el
conector real de la aplicación, porque reparar implica escribir. Eso hace que
``FemagMySQLDatabase.connect()`` ejecute su preparación idempotente del esquema
(``ensure_runtime_schema`` y siembra de medios de pago), que es exactamente el
comportamiento normal de la app al abrirse.

Uso
---

Inspección, no escribe nada::

    py -m scripts.repair_monetary_integrity --budget-number 73

Aplicar, después de revisar el plan::

    py -m scripts.repair_monetary_integrity --budget-number 73 --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from app.services.money import money_sum, money_to_float, quantize_money
from app.services.monetary_audit import (
    BUDGET_HEADER_MISMATCH,
    LEDGER_MATCH_HEADER,
    STATUS_OK,
    Amounts,
    BudgetAudit,
)
from app.services.monetary_audit_readonly import (
    AuditDatabaseTarget,
    MonetaryIntegrityAuditor,
    open_audit_database,
    resolve_audit_database,
)

ACTION_REPAIR = "repair_historical_monetary_integrity"
REASON_REPAIR = "Corrección de inconsistencia monetaria histórica detectada por auditor"
ALREADY_CONSISTENT_MESSAGE = "ALREADY CONSISTENT - no changes applied"

#: Campos monetarios de ``Budget``. Leídos de los modelos reales: la herramienta
#: verifica que existan antes de escribir y jamás toca otro campo.
BUDGET_MONEY_FIELDS = ("net_amount", "discount_amount", "vat_amount", "total_amount")

#: Campos monetarios de ``ClientAccountMovement``. ``amount`` NO entra: guarda el
#: importe documental (0) del que habla ``AccountLedgerService.DOCUMENTAL_AMOUNT``.
MOVEMENT_MONEY_FIELDS = ("net_amount", "discount_amount", "vat_amount", "total_amount")

NOT_TOUCHED_NOTICE = (
    "No se modifica: BudgetItem, LoadOrderProduct, pagos, ajustes, otros movimientos,\n"
    "  ids, fechas, cliente, orden, reference, source_ref, tipo de movimiento ni estado."
)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3


class RepairAborted(Exception):
    """No se puede reparar: falta un identificador o falla una condición."""


#: Veredictos posibles de un presupuesto frente a esta herramienta. Son
#: excluyentes: "reparable" y "ya consistente" nunca se confunden.
REPAIRABLE = "REPAIRABLE"
ALREADY_CONSISTENT = "ALREADY_CONSISTENT"
REFUSED = "REFUSED"


@dataclass(frozen=True)
class RepairVerdict:
    """Resultado de evaluar un presupuesto antes de tocar nada."""

    status: str
    reason: str | None = None

    @property
    def can_repair(self) -> bool:
        return self.status == REPAIRABLE

    @property
    def is_already_consistent(self) -> bool:
        return self.status == ALREADY_CONSISTENT


# ---------------------------------------------------------------------------
# Estructuras
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepairPlan:
    """Qué se cambiaría, con el antes y el después de cada importe."""

    budget_id: int
    budget_number: int
    order_id: int | None
    order_number: int | None
    client_id: int | None
    client_name: str | None
    before_budget: Amounts
    after_budget: Amounts
    movement_id: int
    movement_type: str
    movement_source_ref: str | None
    movement_reference: str | None
    before_movement: Amounts
    after_movement: Amounts

    @property
    def budget_difference(self) -> Amounts:
        return self.after_budget - self.before_budget

    @property
    def movement_difference(self) -> Amounts:
        return self.after_movement - self.before_movement

    @property
    def budget_reference(self) -> str:
        return f"PRES-{self.budget_number:06d}"

    @property
    def order_reference(self) -> str | None:
        return None if self.order_number is None else f"OC-{self.order_number:06d}"


# ---------------------------------------------------------------------------
# Verificación de campos (leídos de los modelos reales)
# ---------------------------------------------------------------------------


def _require_money_fields(model, names: Sequence[str]) -> None:
    """Falla ruidosamente si el modelo cambió y ya no tiene esos campos.

    Se llama antes de escribir: es una defensa contra que un campo monetario se
    renombre y la herramienta pase a actualizar otra cosa en silencio.
    """
    existentes = set(model._meta.fields)
    faltantes = [name for name in names if name not in existentes]
    if faltantes:
        raise RepairAborted(
            f"{model.__name__} no tiene los campos monetarios esperados {faltantes}. "
            "La herramienta no continúa porque escribiría sobre otros campos."
        )


# ---------------------------------------------------------------------------
# Condiciones previas
# ---------------------------------------------------------------------------


def classify_repair(audit: BudgetAudit) -> RepairVerdict:
    """Decide qué se puede hacer con este presupuesto, sin escribir nada.

    Devuelve exactamente uno de estos tres veredictos:

    * ``REPAIRABLE``: se cumplen las cuatro condiciones y la fuente de verdad
      (detalle persistido == estado actual de la orden) está confirmada.
    * ``ALREADY_CONSISTENT``: la cabecera ya coincide con el detalle. No hay nada
      que corregir; esto es lo que hace idempotente la herramienta.
    * ``REFUSED``: falta alguna condición y el motivo queda en ``reason``.
    """
    if audit.budget_integrity == STATUS_OK:
        return RepairVerdict(ALREADY_CONSISTENT)

    if audit.budget_integrity != BUDGET_HEADER_MISMATCH:
        return RepairVerdict(
            REFUSED,
            f"budget_integrity={audit.budget_integrity}; esta herramienta sólo "
            "repara BUDGET_HEADER_MISMATCH.",
        )
    if audit.ledger_integrity != LEDGER_MATCH_HEADER:
        return RepairVerdict(
            REFUSED,
            f"ledger_integrity={audit.ledger_integrity}; se espera "
            "LEDGER_MATCH_HEADER (el débito original arrastra el error de cabecera).",
        )
    if audit.order.order_total_current is None:
        return RepairVerdict(
            REFUSED,
            "El presupuesto no tiene orden de carga, así que no hay estado actual "
            "de orden contra el cual confirmar el detalle.",
        )
    if audit.integrity.detail.total != audit.order.order_total_current:
        return RepairVerdict(
            REFUSED,
            "El detalle no coincide con el total actual de la orden "
            f"({audit.integrity.detail.total} vs {audit.order.order_total_current}). "
            "La fuente de verdad de esta reparación no está confirmada.",
        )
    if len(audit.ledger.movement_ids) != 1:
        return RepairVerdict(
            REFUSED,
            f"Se encontraron {len(audit.ledger.movement_ids)} movimientos originales; "
            "se requiere exactamente uno.",
        )
    return RepairVerdict(REPAIRABLE)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def build_plan(audit: BudgetAudit) -> RepairPlan:
    """Construye el plan. Lanza :class:`RepairAborted` si falta una condición."""
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget

    verdict = classify_repair(audit)
    if verdict.status == ALREADY_CONSISTENT:
        raise RepairAborted(
            "El presupuesto ya es consistente: no hay nada que reparar."
        )
    if not verdict.can_repair:
        raise RepairAborted(verdict.reason or "Condiciones de reparación no cumplidas.")

    _require_money_fields(Budget, BUDGET_MONEY_FIELDS)
    _require_money_fields(ClientAccountMovement, MOVEMENT_MONEY_FIELDS)

    detalle = audit.integrity.detail
    movement = ClientAccountMovement.get_by_id(audit.ledger.movement_ids[0])
    antes_movimiento = Amounts.build(
        net=movement.net_amount,
        discount=movement.discount_amount,
        vat=movement.vat_amount,
        total=movement.total_amount,
    )

    return RepairPlan(
        budget_id=audit.budget_id,
        budget_number=audit.budget_number,
        order_id=audit.order_id,
        order_number=audit.order_number,
        client_id=audit.client_id,
        client_name=audit.client_name,
        before_budget=audit.integrity.header,
        after_budget=detalle,
        movement_id=movement.id,
        movement_type=movement.movement_type,
        movement_source_ref=movement.source_ref,
        movement_reference=movement.reference,
        before_movement=antes_movimiento,
        after_movement=detalle,
    )


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def _amounts_to_columns(amounts: Amounts) -> dict[str, float]:
    """Importes cuantizados a float para persistir, con la política de money.py."""
    return {
        "net_amount": money_to_float(amounts.net),
        "discount_amount": money_to_float(amounts.discount),
        "vat_amount": money_to_float(amounts.vat),
        "total_amount": money_to_float(amounts.total),
    }


def _amounts_to_payload(amounts: Amounts) -> dict[str, float]:
    """Mismos importes con nombres de dominio, para el AuditLog."""
    return {name: float(value) for name, value in amounts.as_dict().items()}


def _detail_amounts(budget_id: int) -> Amounts:
    from app.models.budgets import BudgetItem

    items = list(
        BudgetItem.select()
        .where(BudgetItem.budget == budget_id)
        .order_by(BudgetItem.id)
    )
    return Amounts.build(
        net=money_sum(item.net_subtotal for item in items),
        discount=money_sum(item.discount_amount for item in items),
        vat=money_sum(item.vat_amount for item in items),
        total=money_sum(item.total for item in items),
    )


def verify_postconditions(budget_id: int, movement_id: int) -> list[str]:
    """Invariantes que deben cumplirse ANTES del commit.

    Devuelve la lista de violaciones (vacía si todo cierra). Se evalúa dentro de
    la transacción, con los valores sin confirmar.
    """
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget

    budget = Budget.get_by_id(budget_id)
    movement = ClientAccountMovement.get_by_id(movement_id)
    detail = _detail_amounts(budget_id)
    header = Amounts.build(
        net=budget.net_amount,
        discount=budget.discount_amount,
        vat=budget.vat_amount,
        total=budget.total_amount,
    )

    violations = []
    for nombre, desde_detalle, desde_cabecera in (
        ("net", detail.net, header.net),
        ("discount", detail.discount, header.discount),
        ("vat", detail.vat, header.vat),
        ("total", detail.total, header.total),
    ):
        if desde_detalle != desde_cabecera:
            violations.append(
                f"{nombre}: detalle {desde_detalle} != cabecera {desde_cabecera}"
            )
    movimiento_total = quantize_money(movement.total_amount)
    if movimiento_total != header.total:
        violations.append(
            f"movimiento {movement.id}: {movimiento_total} != cabecera {header.total}"
        )
    return violations


def apply_plan(plan: RepairPlan, *, user: str, reason: str = REASON_REPAIR) -> None:
    """Aplica la reparación en UNA sola transacción.

    Secuencia dentro de la transacción:

    1. actualizar sólo los campos monetarios de ``Budget``;
    2. actualizar sólo los campos monetarios del movimiento original;
    3. verificar las invariantes; si fallan, se aborta;
    4. registrar el ``AuditLog`` con el mecanismo del proyecto.

    Cualquier excepción revierte todo, incluida la auditoría.
    """
    from app.config.database import database_proxy
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget
    from app.services.audit_service import AuditService

    database = database_proxy.obj
    if database is None:
        raise RepairAborted("No hay conexión abierta a la base.")

    columnas_budget = _amounts_to_columns(plan.after_budget)
    columnas_movimiento = _amounts_to_columns(plan.after_movement)

    with database.atomic():
        budget = Budget.get_by_id(plan.budget_id)
        for campo, valor in columnas_budget.items():
            setattr(budget, campo, valor)
        budget.save(only=list(BUDGET_MONEY_FIELDS))

        movement = ClientAccountMovement.get_by_id(plan.movement_id)
        for campo, valor in columnas_movimiento.items():
            setattr(movement, campo, valor)
        movement.save(only=list(MOVEMENT_MONEY_FIELDS))

        violations = verify_postconditions(plan.budget_id, plan.movement_id)
        if violations:
            raise RepairAborted(
                "Postcondición incumplida, se revierte todo: " + "; ".join(violations)
            )

        AuditService().record(
            user=user,
            module="Presupuestos",
            action=ACTION_REPAIR,
            record_ref=f"Budget:{plan.budget_id}",
            old_value={
                "budget_total": float(plan.before_budget.total),
                "ledger_total": float(plan.before_movement.total),
            },
            new_value={
                "budget_id": plan.budget_id,
                "budget_number": plan.budget_number,
                "order_id": plan.order_id,
                "order_number": plan.order_number,
                "client_id": plan.client_id,
                "movement_id": plan.movement_id,
                "before_budget": _amounts_to_payload(plan.before_budget),
                "after_budget": _amounts_to_payload(plan.after_budget),
                "before_ledger": _amounts_to_payload(plan.before_movement),
                "after_ledger": _amounts_to_payload(plan.after_movement),
                "difference": float(plan.budget_difference.total),
            },
            observation=reason,
        )


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


def _money(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:,.2f}"


def _linea(nombre: str, antes: Decimal, despues: Decimal, diferencia: Decimal) -> str:
    return (
        f"  {nombre + ':':<10} BEFORE {_money(antes):>18}  ->  "
        f"AFTER {_money(despues):>18}   DIFF {_money(diferencia):>14}"
    )


def render_plan(plan: RepairPlan) -> str:
    """Plan legible. No escribe nada: es la salida del DRY-RUN."""
    before_b = plan.before_budget
    after_b = plan.after_budget
    diff_b = plan.budget_difference
    before_m = plan.before_movement
    after_m = plan.after_movement
    diff_m = plan.movement_difference

    lines = [
        "REPAIR PLAN",
        "===========",
        "",
        "Budget:",
        f"  id:            {plan.budget_id}",
        f"  number:        {plan.budget_reference}",
        f"  order:         {plan.order_reference or '-'} (id {plan.order_id if plan.order_id is not None else '-'})",
        f"  client:        {plan.client_name or '-'} (id {plan.client_id if plan.client_id is not None else '-'})",
        "",
        "Budget header:",
        _linea("net", before_b.net, after_b.net, diff_b.net),
        _linea("discount", before_b.discount, after_b.discount, diff_b.discount),
        _linea("vat", before_b.vat, after_b.vat, diff_b.vat),
        _linea("total", before_b.total, after_b.total, diff_b.total),
        "",
        "Ledger movement:",
        f"  id:            {plan.movement_id}",
        f"  type:          {plan.movement_type}",
        f"  source_ref:    {plan.movement_source_ref or '-'}",
        f"  reference:     {plan.movement_reference or '-'}",
        _linea("net", before_m.net, after_m.net, diff_m.net),
        _linea("discount", before_m.discount, after_m.discount, diff_m.discount),
        _linea("vat", before_m.vat, after_m.vat, diff_m.vat),
        _linea("total", before_m.total, after_m.total, diff_m.total),
        "",
        NOT_TOUCHED_NOTICE,
    ]
    return "\n".join(lines)


def render_verification(audit: BudgetAudit) -> str:
    """Estado del auditor después de la reparación (o tras un no-op)."""
    return "\n".join(
        [
            "VERIFY (auditor)",
            f"  budget_integrity:            {audit.budget_integrity}",
            f"  ledger_integrity:            {audit.ledger_integrity}",
            f"  ledger_matches_header:       {audit.ledger.ledger_matches_header}",
            f"  ledger_matches_detail:       {audit.ledger.ledger_matches_detail}",
            f"  potential_financial_difference: {audit.potential_financial_difference:.2f}",
            f"  severity:                    {audit.severity}",
        ]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.repair_monetary_integrity",
        description=(
            "Reparacion controlada de UN presupuesto historico con inconsistencia "
            "monetaria confirmada. DRY-RUN por defecto; requiere --apply para "
            "escribir. No repara en lote ni por lote automatico."
        ),
    )
    parser.add_argument(
        "--budget", type=str, help="Id interno del presupuesto a reparar."
    )
    parser.add_argument(
        "--budget-number", type=str, help="Numero visible del presupuesto (73 = PRES-000073)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Escribir la reparacion. Sin este flag no se modifica nada.",
    )
    parser.add_argument(
        "--user", default="reparacion-monetaria", help="Usuario que queda en el AuditLog."
    )
    parser.add_argument(
        "--db", metavar="NOMBRE", help="Auditar otra base del mismo servidor (por ejemplo, la copia local)."
    )
    return parser


def _parse_single_identifier(argv: Sequence[str] | None) -> tuple[argparse.Namespace, int]:
    """Exige exactamente un identificador explícito. Sin lote, sin comodines."""
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv if argv is not None else []))
    except SystemExit as exc:
        raise RepairAborted(
            "Argumentos inválidos. Use exactamente un identificador: "
            "--budget <id> o --budget-number <numero>."
        ) from exc

    dados = [valor for valor in (args.budget, args.budget_number) if valor is not None]
    if len(dados) != 1:
        raise RepairAborted(
            "Se requiere exactamente UN identificador explícito "
            "(--budget <id> o --budget-number <numero>). "
            "No existe reparación en lote, por comodín ni automática: "
            "cada caso se revisa y se aplica uno por uno."
        )
    valor = str(dados[0]).strip()
    if not valor.isdigit() or int(valor) <= 0:
        raise RepairAborted(
            f"El identificador {valor!r} no es un entero positivo válido."
        )
    identificador = int(valor)
    if args.budget is not None:
        return args, identificador
    return args, identificador


def audit_budget(*, budget_id: int | None = None, budget_number: int | None = None):
    """Reusa la clasificación del auditor READ-ONLY, sin tocar el auditor."""
    audits = MonetaryIntegrityAuditor().run(
        budget_id=budget_id, budget_number=budget_number
    )
    return audits[0] if audits else None


def open_writable_database(target: AuditDatabaseTarget):
    """Abre la MISMA base resuelta, pero con el motor escribible de la app.

    A diferencia del auditor, aquí se usa el conector real
    (``FemagMySQLDatabase``) porque la operación ES una escritura. Su
    ``connect()`` ejecuta la preparación idempotente del esquema, que es el
    comportamiento normal de la aplicación.
    """
    from app.config.database import (
        FemagMySQLDatabase,
        bind_database,
        resolve_mysql_host_ipv4,
    )
    from peewee import SqliteDatabase

    if target.engine == "mysql":
        database = FemagMySQLDatabase(
            target.database,
            host=resolve_mysql_host_ipv4(target.host),
            port=target.port,
            user=target.user,
            password=target.password,
            charset="utf8mb4",
        )
    else:
        database = SqliteDatabase(str(target.sqlite_path), pragmas={"foreign_keys": 1})
    bind_database(database)
    database.connect(reuse_if_open=True)
    return database


def _print_connection(target: AuditDatabaseTarget) -> None:
    for line in target.header_lines():
        print(line)
    print("WRITE MODE: destructivo y explícito (una sola transacción)")


def run_repair(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la herramienta. Devuelve el código de salida.

    ``0`` plan mostrado, ya consistente o reparación aplicada.
    ``2`` error de configuración o conexión.
    ``3`` aborto por condición de seguridad.
    """
    args, identificador = _parse_single_identifier(argv)

    por_id = args.budget is not None
    target = resolve_audit_database(database_name=args.db)
    _print_connection(target)

    database = open_writable_database(target)
    try:
        if por_id:
            audit = audit_budget(budget_id=identificador)
        else:
            audit = audit_budget(budget_number=identificador)
        if audit is None:
            raise RepairAborted(
                f"No se encontró el presupuesto {identificador} en "
                f"{target.database or target.sqlite_path}."
            )

        verdict = classify_repair(audit)
        if verdict.is_already_consistent:
            print(ALREADY_CONSISTENT_MESSAGE)
            print(render_verification(audit))
            return EXIT_OK
        if not verdict.can_repair:
            raise RepairAborted(verdict.reason or "Condiciones no cumplidas.")

        plan = build_plan(audit)

        if not args.apply:
            print("DRY-RUN: no se modificó nada.")
            print(render_plan(plan))
            print("")
            print("Para aplicar exactamente este plan, vuelva a ejecutar con --apply.")
            return EXIT_OK

        apply_plan(plan, user=args.user)
        print("APPLIED")
        print(render_verification(audit_budget(budget_id=plan.budget_id)))
        return EXIT_OK
    finally:
        try:
            database.close()
        except Exception:  # pragma: no cover - cierre defensivo
            pass


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run_repair(argv)
    except RepairAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return EXIT_ABORTED
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}. "
            "No se aplicó ningún cambio; la transacción se revirtió.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

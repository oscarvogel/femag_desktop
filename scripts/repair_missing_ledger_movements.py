"""Reparación de órdenes de carga emitidas SIN cuenta corriente ni salida de stock.

Una emisión de orden de carga deja tres efectos: el estado "Emitida", el
movimiento en la cuenta corriente del cliente y el descuento de stock. Con
``#726`` esos tres efectos quedaron en una sola transacción, pero las órdenes
que ya quedaron a medias (OC-000078 y OC-000081 en producción) necesitan una
reparación **sin rehacer la operación física**: la mercadería ya salió de la
planta.

Esta herramienta:

1. **Detecta** las órdenes emitidas o cerradas cuyo presupuesto no tiene
   movimiento en la cuenta corriente, o cuya mercadería no salió del stock.
2. **Repara** con los mismos servicios que usa la emisión
   (:class:`AccountLedgerService` y :class:`LoadOrderStockService`), que son
   idempotentes: repetirlos no duplica nada.

Política
--------

1. **DRY-RUN por defecto.** ``--apply`` es obligatorio para escribir.
2. **Una orden por ejecución.** No hay lote ni comodín: cada caso se revisa y
   se aplica de a uno, igual que ``scripts/repair_monetary_integrity.py``.
3. **Idempotente.** Una orden ya reparada no se toca, no genera un segundo
   movimiento y no duplica el ``AuditLog``.
4. **Una sola transacción.** Estado, cuenta corriente, stock y auditoría se
   escriben juntos: si algo falla, se revierte todo.
5. **No toca** importes: los movimientos salen del presupuesto ya emitido, que
   es la fuente de verdad del sistema.

Uso
---

Ver qué órdenes están rotas, sin escribir nada::

    py -m scripts.repair_missing_ledger_movements --list

Ver el plan de una orden concreta::

    py -m scripts.repair_missing_ledger_movements --order 78

Aplicar, después de revisar el plan::

    py -m scripts.repair_missing_ledger_movements --order 78 --apply
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Sequence

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3

#: Estados de orden que pueden tener movimientos de cuenta corriente vivos.
REPAIRABLE_STATUSES = ("Emitida", "Cerrada")


class RepairAborted(Exception):
    """No se puede reparar: falta un identificador o falla una condición."""


@dataclass(frozen=True)
class BudgetGap:
    """Un presupuesto de la orden al que le falta su movimiento."""

    budget_id: int
    budget_number: str
    client_id: int
    client_name: str
    timing: str
    total_amount: float


@dataclass(frozen=True)
class OrderFinding:
    """Todo lo que falta registrar de una orden."""

    order_id: int
    order_number: int
    status: str
    date: str
    budget_gaps: tuple[BudgetGap, ...]
    missing_stock: bool
    stock_units: int
    stock_kg: float

    @property
    def is_repairable(self) -> bool:
        return bool(self.budget_gaps) or self.missing_stock


# ---------------------------------------------------------------------------
# Detección
# ---------------------------------------------------------------------------
def _clients_of(order) -> list:
    from app.models.masters import Client

    clients, vistos = [], set()
    for destino in order.destinations.order_by():
        cliente_id = destino.client_id
        if cliente_id in vistos:
            continue
        vistos.add(cliente_id)
        clientes.append(Client.get_by_id(cliente_id))
    return clientes


def _budgets_of(order) -> list:
    from app.models.budgets import Budget

    return list(
        Budget.select()
        .where(
            (Budget.load_order == order)
            & (Budget.origin == Budget.ORIGIN_LOAD_ORDER)
        )
        .order_by(Budget.id)
    )


def _movement_of_budget(budget_id: int):
    from app.models.accounting import ClientAccountMovement

    return (
        ClientAccountMovement.select()
        .where(
            (ClientAccountMovement.source_ref == f"Budget:{budget_id}")
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        )
        .order_by(ClientAccountMovement.id)
        .first()
    )


def _dispatch_movements(order_id: int) -> list:
    from app.models.stock import StockMovement
    from app.services.load_order_stock_service import dispatch_source_prefix

    return list(
        StockMovement.select().where(
            StockMovement.source_ref.startswith(f"{dispatch_source_prefix(order_id)}:")
        )
    )


def find_missing_ledger(order, *, current_user: str = "auditoria") -> OrderFinding:
    """Detecta qué le falta registrar a una orden. No escribe nada."""
    from app.services.load_order_stock_service import LoadOrderStockService

    gaps: list[BudgetGap] = []
    for budget in _budgets_of(order):
        if _movement_of_budget(budget.id) is not None:
            continue
        cliente = budget.client
        gaps.append(
            BudgetGap(
                budget_id=budget.id,
                budget_number=budget.display_number,
                client_id=cliente.id,
                client_name=cliente.name,
                timing=budget.timing,
                total_amount=float(budget.total_amount or 0),
            )
        )

    plan = LoadOrderStockService(current_user=current_user).plan_dispatch(order)
    despachos = _dispatch_movements(order.id)
    unidades = int(sum(float(unidades) for _producto, unidades, _kilos in plan))
    kilos = float(sum(float(kilos) for _producto, _unidades, kilos in plan))

    return OrderFinding(
        order_id=order.id,
        order_number=int(order.order_number),
        status=order.status,
        date=str(order.date),
        budget_gaps=tuple(gaps),
        missing_stock=bool(plan) and not despachos,
        stock_units=unidades,
        stock_kg=kilos,
    )


def find_all(current_user: str = "auditoria") -> list[OrderFinding]:
    """Todas las ordenes con faltantes. No escribe nada."""
    from app.models.load_orders import LoadOrder

    findings = []
    for order in (
        LoadOrder.select()
        .where(LoadOrder.status.in_(REPAIRABLE_STATUSES))
        .order_by(LoadOrder.order_number)
    ):
        finding = find_missing_ledger(order, current_user=current_user)
        if finding.is_repairable:
            findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def _money(value: float) -> str:
    return f"{value:,.2f}"


def render_finding(finding: OrderFinding) -> str:
    """Informe legible de una orden. No escribe nada."""
    lines = [
        f"OC-{finding.order_number:06d} (id {finding.order_id})  estado={finding.status}  fecha={finding.date}",
    ]
    if finding.budget_gaps:
        lines.append("  Cuenta corriente: falta el movimiento de")
        for gap in finding.budget_gaps:
            lines.append(
                f"    - {gap.budget_number}  cliente={gap.client_name} (id {gap.client_id})  "
                f"parte={gap.timing}  total={_money(gap.total_amount)}"
            )
    else:
        lines.append("  Cuenta corriente: completa")
    if finding.missing_stock:
        lines.append(
            f"  Stock: falta el despacho de {finding.stock_units} unidad(es) / {finding.stock_kg:,.3f} kg"
        )
    else:
        lines.append("  Stock: despacho registrado")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reparación
# ---------------------------------------------------------------------------
def repair_order(order, *, user: str) -> dict:
    """Repara UNA orden en una sola transacción.

    Usa los mismos servicios que la emisión, que son idempotentes: si el
    movimiento o el descuento ya estaban, no se duplican.
    """
    from app.config.database import database_proxy
    from app.services.account_ledger_service import AccountLedgerService
    from app.services.audit_service import AuditService
    from app.services.load_order_stock_service import LoadOrderStockService

    resultado = {"movimientos": [], "despachos": [], "presupuestos": 0}
    with database_proxy.atomic():
        presupuestos = _budgets_of(order)
        resultado["presupuestos"] = len(presupuestos)
        movimientos = AccountLedgerService(current_user=user).generate_for_load_order(order)
        resultado["movimientos"] = [m.id for m in movimientos]
        despachos = LoadOrderStockService(current_user=user).register_dispatch(order)
        resultado["despachos"] = [m.id for m in despachos]
        AuditService().record(
            user=user,
            module="Ordenes de carga",
            action="reparar_cuenta_corriente",
            record_ref=f"LoadOrder:{order.id}",
            new_value={
                "order_number": int(order.order_number),
                "movement_ids": resultado["movimientos"],
                "stock_movement_ids": resultado["despachos"],
            },
            observation="Reparacion de emision parcial (#726)",
        )
    return resultado


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.repair_missing_ledger_movements",
        description=(
            "Detecta y repara ordenes de carga emitidas sin movimiento en la "
            "cuenta corriente o sin salida de stock. DRY-RUN por defecto; "
            "requiere --apply para escribir. No repara en lote."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Listar todas las ordenes con faltantes. No escribe nada.",
    )
    parser.add_argument(
        "--order",
        type=str,
        help="Numero visible de la orden (78 = OC-000078) o su id interno.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Escribir la reparacion. Sin este flag no se modifica nada.",
    )
    parser.add_argument(
        "--user", default="reparacion-cuenta-corriente", help="Usuario que queda en el AuditLog."
    )
    parser.add_argument(
        "--db", metavar="NOMBRE", help="Reparar otra base del mismo servidor (por ejemplo, la copia local)."
    )
    return parser


def _resolve_order(reference: str):
    from app.models.load_orders import LoadOrder

    valor = str(reference).strip()
    if not valor.isdigit() or int(valor) <= 0:
        raise RepairAborted(f"El identificador {reference!r} no es un entero positivo valido.")
    numero = int(valor)
    order = LoadOrder.get_or_none(LoadOrder.order_number == numero)
    if order is None:
        order = LoadOrder.get_or_none(LoadOrder.id == numero)
    if order is None:
        raise RepairAborted(f"No se encontro la orden {valor}.")
    if order.status not in REPAIRABLE_STATUSES:
        raise RepairAborted(
            f"La OC-{order.order_number:06d} esta en estado {order.status}: "
            f"solo se reparan ordenes {', '.join(REPAIRABLE_STATUSES)}."
        )
    return order


def run(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la herramienta. Devuelve el codigo de salida."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        raise RepairAborted(
            "Argumentos invalidos. Use --list para ver todas las ordenes o "
            "--order <numero> para trabajar una."
        ) from exc

    if args.list == bool(args.order):
        raise RepairAborted(
            "Use --list para ver todas las ordenes con faltantes o --order <numero> "
            "para trabajar una sola. No se repara en lote ni por defecto."
        )

    from app.services.monetary_audit_readonly import resolve_audit_database

    try:
        target = resolve_audit_database(database_name=args.db)
    except Exception as exc:
        print(
            f"ERROR: no se pudo resolver la conexion de FEMAG: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    for line in target.header_lines():
        print(line)
    print("WRITE MODE: destructivo y explicito (una sola transaccion)" if args.apply else "READ MODE: no se modifica nada")

    from scripts.repair_monetary_integrity import open_writable_database

    database = open_writable_database(target)
    try:
        if args.list:
            findings = find_all(current_user=args.user)
            if not findings:
                print("No hay ordenes emitidas sin cuenta corriente ni sin salida de stock.")
                return EXIT_OK
            for finding in findings:
                print(render_finding(finding))
            print("")
            print(f"{len(findings)} orden(es) con faltantes. Para reparar una: --order <numero> --apply")
            return EXIT_OK

        order = _resolve_order(args.order)
        finding = find_missing_ledger(order, current_user=args.user)
        print(render_finding(finding))
        if not finding.is_repairable:
            print("")
            print("ALREADY CONSISTENT - no changes applied")
            return EXIT_OK

        if not args.apply:
            print("")
            print("DRY-RUN: no se modifico nada.")
            print("Para aplicar exactamente este plan, vuelva a ejecutar con --apply.")
            return EXIT_OK

        resultado = repair_order(order, user=args.user)
        print("")
        print("APPLIED")
        print(
            f"  movimientos de cuenta corriente: {resultado['movimientos'] or 'ninguno (ya estaban)'}"
        )
        print(f"  despachos de stock: {resultado['despachos'] or 'ninguno (ya estaba)'}")
        print("")
        print(render_finding(find_missing_ledger(order, current_user=args.user)))
        return EXIT_OK
    finally:
        try:
            database.close()
        except Exception:  # pragma: no cover - cierre defensivo
            pass


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except RepairAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return EXIT_ABORTED
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}. "
            "No se aplico ningun cambio; la transaccion se revirtio.",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())

"""Reparación por consola de presupuestos de clientes que ya no están en la orden.

La reparación normal es automática: al imprimir una orden pendiente o al
emitirla, ``BudgetService`` anula los presupuestos de los clientes que se
quitaron de la orden. Esta herramienta sirve para los casos históricos, como
la OC-000104, donde el presupuesto quedó activo después de una edición.

Política
--------

1. **DRY-RUN por defecto.** ``--apply`` es obligatorio para escribir.
2. **Una orden por ejecución.** ``--list`` muestra todas, pero no repara en lote.
3. **No toca presupuestos con movimiento contable o estado aplicado.**
4. **No borra:** anula el presupuesto y deja auditoría.
5. **Idempotente:** volver a correrla no cambia nada.

Uso
---

Ver todos los presupuestos huérfanos::

    py -m scripts.repair_stale_load_order_budgets --list

Ver el plan de una orden::

    py -m scripts.repair_stale_load_order_budgets --order 104

Aplicar después de revisar::

    py -m scripts.repair_stale_load_order_budgets --order 104 --apply
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3


class RepairAborted(Exception):
    """No se puede reparar: falta un identificador o falla una condición."""


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _resolve_order(reference: str):
    from app.models.load_orders import LoadOrder

    value = str(reference).strip()
    if not value.isdigit() or int(value) <= 0:
        raise RepairAborted(f"El identificador {reference!r} no es un entero positivo válido.")
    number = int(value)
    order = LoadOrder.get_or_none(LoadOrder.order_number == number)
    if order is None:
        order = LoadOrder.get_or_none(LoadOrder.id == number)
    if order is None:
        raise RepairAborted(f"No se encontró la orden {value}.")
    return order


def _describe(budget) -> str:
    from app.models.load_orders import LoadOrderBudgetStatus

    applied = (
        LoadOrderBudgetStatus.select()
        .where(
            (LoadOrderBudgetStatus.order == budget.load_order)
            & (LoadOrderBudgetStatus.client == budget.client)
            & (LoadOrderBudgetStatus.timing == budget.timing)
            & (LoadOrderBudgetStatus.status == LoadOrderBudgetStatus.STATUS_APPLIED)
        )
        .exists()
    )
    has_movement = budget.account_movements.exists()
    protection = []
    if has_movement:
        protection.append("con movimiento contable")
    if applied:
        protection.append("con estado aplicado")
    suffix = f"  [{', '.join(protection)}]" if protection else ""
    return (
        f"  {budget.display_number}  orden={budget.load_order_reference or '-'}  "
        f"cliente={budget.client.name} (id {budget.client_id})  "
        f"parte={budget.timing}  total={_money(budget.total_amount)}{suffix}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.repair_stale_load_order_budgets",
        description=(
            "Detecta y anula presupuestos de clientes que ya no tienen mercadería "
            "en la orden. DRY-RUN por defecto; requiere --apply para escribir."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Listar todos los presupuestos huérfanos. No escribe nada.",
    )
    parser.add_argument(
        "--order",
        type=str,
        help="Número visible de la orden (104 = OC-000104) o su id interno.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Escribir la reparación. Sin este flag no se modifica nada.",
    )
    parser.add_argument(
        "--user",
        default="reparacion-presupuestos",
        help="Usuario que queda en el AuditLog.",
    )
    parser.add_argument(
        "--db",
        metavar="NOMBRE",
        help="Reparar otra base del mismo servidor (por ejemplo, la copia local).",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        raise RepairAborted(
            "Argumentos inválidos. Use --list o --order <número>."
        ) from exc

    if args.list == bool(args.order):
        raise RepairAborted(
            "Use --list para ver todos los casos o --order <número> para trabajar uno."
        )
    if args.apply and args.list:
        raise RepairAborted("--apply requiere --order. No se repara en lote.")

    from app.services.monetary_audit_readonly import resolve_audit_database

    try:
        target = resolve_audit_database(database_name=args.db)
    except Exception as exc:
        print(
            f"ERROR: no se pudo resolver la conexión de FEMAG: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    for line in target.header_lines():
        print(line)
    print(
        "WRITE MODE: explícito (una sola transacción)"
        if args.apply
        else "READ MODE: no se modifica nada"
    )

    from scripts.repair_monetary_integrity import open_writable_database

    database = open_writable_database(target)
    try:
        from app.services.budget_service import BudgetService

        service = BudgetService(current_user=args.user)
        if args.list:
            stale = service.find_stale_load_order_budgets()
            if not stale:
                print("No hay presupuestos de clientes que ya no estén en la orden.")
                return EXIT_OK
            for budget in stale:
                print(_describe(budget))
            print("")
            print(
                f"{len(stale)} presupuesto(s) huérfano(s). "
                "Para reparar uno: --order <número> --apply"
            )
            return EXIT_OK

        order = _resolve_order(args.order)
        stale = service.find_stale_load_order_budgets(order)
        print(f"{order.status}  {order.date}  OC-{order.order_number:06d} (id {order.id})")
        if not stale:
            print("Sin presupuestos huérfanos. No hay nada para reparar.")
            return EXIT_OK
        for budget in stale:
            print(_describe(budget))

        if not args.apply:
            print("")
            print("DRY-RUN: no se modificó nada.")
            print("Para aplicar exactamente este plan, vuelva a ejecutar con --apply.")
            return EXIT_OK

        annulled = service.annul_stale_load_order_budgets(order, allow_issued=True)
        print("")
        print("APPLIED")
        print(f"  presupuestos anulados: {len(annulled)}")
        for budget in annulled:
            print(f"    {budget.display_number}  cliente={budget.client.name}")
        print("")
        for budget in service.find_stale_load_order_budgets(order):
            print(_describe(budget))
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
            "No se aplicó ningún cambio; la transacción se revirtió.",
            file=sys.stderr,
        )
        return EXIT_ABORTED


if __name__ == "__main__":
    raise SystemExit(main())

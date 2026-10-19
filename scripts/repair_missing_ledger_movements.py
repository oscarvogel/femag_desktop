"""Reparación por consola de órdenes de carga emitidas SIN cuenta corriente.

La vía normal es la aplicación: botón **"Reparar cta. corriente"** en la
pantalla de órdenes, que abre el diálogo de administración
(:class:`app.ui.load_order_ledger_repair_dialog.LoadOrderLedgerRepairDialog`).
Esta herramienta es el complemento de consola, para el puesto donde se atiende
el problema sin usuario gráfico o para dejar registro de la operación.

La lógica vive en :class:`app.services.load_order_ledger_repair_service.
LoadOrderLedgerRepairService`: la herramienta y la pantalla usan exactamente la
misma.

Política
--------

1. **DRY-RUN por defecto.** ``--apply`` es obligatorio para escribir.
2. **Una orden por ejecución.** No hay lote ni comodín: cada caso se revisa y
   se aplica de a uno, igual que ``scripts/repair_monetary_integrity.py``.
3. **Idempotente.** Una orden ya reparada no se toca, no genera un segundo
   movimiento y no duplica el ``AuditLog``.
4. **Una sola transacción.** Cuenta corriente, stock y auditoría se escriben
   juntos: si algo falla, se revierte todo.
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
from typing import Sequence

from app.services.load_order_ledger_repair_service import (
    LoadOrderLedgerRepairService,
    OrderLedgerGap,
)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3


class RepairAborted(Exception):
    """No se puede reparar: falta un identificador o falla una condición."""


def _money(value: float) -> str:
    return f"{value:,.2f}"


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------
def render_finding(finding: OrderLedgerGap) -> str:
    """Informe legible de una orden. No escribe nada."""
    lines = [
        f"{finding.order_reference} (id {finding.order_id})  estado={finding.status}  fecha={finding.date}",
    ]
    if finding.ledger_gaps:
        lines.append("  Cuenta corriente: falta el movimiento de")
        for gap in finding.ledger_gaps:
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
    print(
        "WRITE MODE: destructivo y explicito (una sola transaccion)"
        if args.apply
        else "READ MODE: no se modifica nada"
    )

    from scripts.repair_monetary_integrity import open_writable_database

    database = open_writable_database(target)
    try:
        service = LoadOrderLedgerRepairService(current_user=args.user)

        if args.list:
            findings = service.find_broken_orders()
            if not findings:
                print("No hay ordenes emitidas sin cuenta corriente ni sin salida de stock.")
                return EXIT_OK
            for finding in findings:
                print(render_finding(finding))
            print("")
            print(
                f"{len(findings)} orden(es) con faltantes. Para reparar una: --order <numero> --apply"
            )
            return EXIT_OK

        order = _resolve_order(args.order)
        finding = service.find_gap(order)
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

        result = service.repair(order)
        print("")
        print("APPLIED")
        print(
            f"  movimientos de cuenta corriente: {len(result.movement_ids) or 'ninguno (ya estaban)'}"
        )
        print(f"  despachos de stock: {len(result.stock_movement_ids) or 'ninguno (ya estaba)'}")
        print("")
        print(render_finding(service.find_gap(order)))
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

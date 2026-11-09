"""Corrige la fecha de un movimiento de cuenta corriente con auditoría.

Pensado para casos puntuales como el #899: un movimiento manual cargado con
una fecha de otro año. DRY-RUN por defecto; requiere ``--apply`` para escribir.

Uso
---

Ver el plan::

    py -m scripts.repair_account_movement_date --movement 414 --date 2026-08-31

Aplicar::

    py -m scripts.repair_account_movement_date --movement 414 --date 2026-08-31 --apply

Sólo acepta movimientos manuales (débito, crédito) o saldos iniciales. No toca
pagos, documentos de orden ni movimientos de stock.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from typing import Sequence

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3


class RepairAborted(Exception):
    """No se puede reparar: falta un dato o falla una condición."""


def _money(value) -> str:
    return f"{float(value or 0):,.2f}"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise RepairAborted(f"La fecha {value!r} no tiene formato AAAA-MM-DD.") from exc


def _resolve_movement(reference: str):
    from app.models.accounting import ClientAccountMovement

    value = str(reference).strip()
    if not value.isdigit() or int(value) <= 0:
        raise RepairAborted(f"El identificador {reference!r} no es un id válido.")
    movement = ClientAccountMovement.get_or_none(
        ClientAccountMovement.id == int(value)
    )
    if movement is None:
        raise RepairAborted(f"No se encontró el movimiento {value}.")
    allowed = {
        ClientAccountMovement.TYPE_MANUAL_DEBIT,
        ClientAccountMovement.TYPE_MANUAL_CREDIT,
        ClientAccountMovement.TYPE_OPENING_BALANCE,
    }
    if movement.movement_type not in allowed:
        raise RepairAborted(
            f"El movimiento {movement.id} es {movement.movement_type}; "
            "esta herramienta sólo corrige débitos/créditos manuales y saldos iniciales."
        )
    return movement


def _client_balance(client_id: int) -> Decimal:
    from app.models.accounting import ClientAccountMovement
    from peewee import fn

    value = (
        ClientAccountMovement.select(fn.SUM(ClientAccountMovement.total_amount))
        .where(ClientAccountMovement.client == client_id)
        .scalar()
    )
    return Decimal(str(value or 0))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.repair_account_movement_date",
        description=(
            "Corrige la fecha de un movimiento de cuenta corriente y deja "
            "auditoría. DRY-RUN por defecto."
        ),
    )
    parser.add_argument("--movement", required=True, help="Id del movimiento.")
    parser.add_argument("--date", required=True, help="Nueva fecha AAAA-MM-DD.")
    parser.add_argument("--apply", action="store_true", help="Escribir el cambio.")
    parser.add_argument(
        "--reason",
        default="Corrección de fecha por error de carga.",
        help="Motivo que queda en la auditoría.",
    )
    parser.add_argument(
        "--user",
        default="reparacion-fecha-movimiento",
        help="Usuario que queda en la auditoría.",
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
        raise RepairAborted("Argumentos inválidos.") from exc

    new_date = _parse_date(args.date)
    from app.services.account_date_rules import AccountDateError, validate_movement_date

    try:
        validate_movement_date(new_date)
    except AccountDateError as exc:
        raise RepairAborted(str(exc)) from exc

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
    print("WRITE MODE: explícito" if args.apply else "READ MODE: no se modifica nada")

    from scripts.repair_monetary_integrity import open_writable_database

    database = open_writable_database(target)
    try:
        from app.services.account_ledger_service import AccountLedgerService

        movement = _resolve_movement(args.movement)
        balance_before = _client_balance(movement.client_id)

        print(
            f"Movimiento {movement.id}: {movement.movement_type}  "
            f"cliente={movement.client.name} (id {movement.client_id})  "
            f"importe={_money(movement.total_amount)}  "
            f"descripción={movement.description!r}"
        )
        print(f"Fecha actual:  {movement.movement_date}")
        print(f"Fecha nueva:   {new_date}")
        print(f"Saldo cliente: {_money(balance_before)}")

        if movement.movement_date == new_date:
            print("Sin cambios: el movimiento ya tiene esa fecha.")
            return EXIT_OK

        if not args.apply:
            print("")
            print("DRY-RUN: no se modificó nada.")
            print("Para aplicar exactamente este cambio, vuelva a ejecutar con --apply.")
            return EXIT_OK

        AccountLedgerService(current_user=args.user).correct_movement_date(
            movement, new_date, reason=args.reason
        )
        movement = type(movement).get_by_id(movement.id)
        balance_after = _client_balance(movement.client_id)
        print("")
        print("APPLIED")
        print(f"Fecha nueva:   {movement.movement_date}")
        print(f"Saldo cliente: {_money(balance_after)}")
        if balance_after != balance_before:
            print("ADVERTENCIA: el saldo cambió. Revise antes de continuar.", file=sys.stderr)
            return EXIT_ABORTED
        print("Auditoría: corregir_fecha_movimiento")
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

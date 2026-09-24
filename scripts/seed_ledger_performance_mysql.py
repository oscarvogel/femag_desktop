from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Salesperson
from scripts.performance_mysql_common import (
    connect_performance_database,
    ensure_mysql_database,
    performance_db_config,
)


def _chunks(rows: list[dict], size: int = 2000):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _insert_many(model, rows: list[dict], *, chunk_size: int = 2000) -> None:
    for chunk in _chunks(rows, chunk_size):
        model.insert_many(chunk).execute()


def seed_ledger_data(
    *,
    client_count: int,
    movements_per_client: int,
    salesperson_count: int,
) -> dict[str, int]:
    if client_count < 1:
        raise ValueError("--clients debe ser mayor a cero.")
    if movements_per_client < 1:
        raise ValueError("--movements-per-client debe ser mayor a cero.")
    if salesperson_count < 1:
        raise ValueError("--salespeople debe ser mayor a cero.")

    today = date.today()

    salespeople_rows = [
        {
            "name": f"PERF Vendedor {index + 1:03d}",
            "phone": f"3764{index + 1:06d}",
            "active": True,
        }
        for index in range(salesperson_count)
    ]
    _insert_many(Salesperson, salespeople_rows)
    salespeople = list(Salesperson.select().order_by(Salesperson.id))

    client_rows = []
    for index in range(client_count):
        salesperson = None if index % 17 == 0 else salespeople[index % salesperson_count]
        client_rows.append(
            {
                "name": f"PERF Ledger Cliente {index + 1:06d}",
                "cuit": f"30{700000000 + index:09d}",
                "iva_condition": "RI",
                "phone": f"3764{100000 + index:06d}",
                "salesperson": salesperson.id if salesperson is not None else None,
                "active": True,
            }
        )
    _insert_many(Client, client_rows)
    clients = list(Client.select(Client.id).order_by(Client.id))

    inserted_movements = 0
    pending: list[dict] = []
    for client_index, client in enumerate(clients):
        for movement_index in range(movements_per_client):
            positive = movement_index % 5 in (0, 1, 2)
            base = 10_000 + ((client_index * 37 + movement_index * 113) % 90_000)
            amount = float(base if positive else -(base * 0.45))
            movement_date = today - timedelta(days=(movement_index * 3 + client_index) % 365)

            due_date = None
            if positive:
                bucket = movement_index % 3
                if bucket == 0:
                    due_date = today - timedelta(days=1 + (movement_index % 90))
                elif bucket == 1:
                    due_date = today + timedelta(days=1 + (movement_index % 7))
                else:
                    due_date = today + timedelta(days=8 + (movement_index % 60))

            pending.append(
                {
                    "client": client.id,
                    "movement_type": (
                        ClientAccountMovement.TYPE_MANUAL_DEBIT
                        if positive
                        else ClientAccountMovement.TYPE_PAYMENT
                    ),
                    "amount": amount,
                    "net_amount": amount,
                    "discount_amount": 0.0,
                    "vat_amount": 0.0,
                    "total_amount": amount,
                    "currency": "ARS",
                    "movement_date": movement_date,
                    "due_date": due_date,
                    "description": "Movimiento generado para benchmark de cuenta corriente",
                    "source_ref": f"PERF-LEDGER:{client.id}:{movement_index}",
                    "reference": f"PERF-{client.id}-{movement_index}",
                    "is_reversal": False,
                    "created_by": "performance",
                }
            )
            if len(pending) >= 5000:
                _insert_many(ClientAccountMovement, pending, chunk_size=5000)
                inserted_movements += len(pending)
                pending.clear()

    if pending:
        _insert_many(ClientAccountMovement, pending, chunk_size=5000)
        inserted_movements += len(pending)

    return {
        "salespeople": salesperson_count,
        "clients": client_count,
        "unassigned_clients": (client_count + 16) // 17,
        "movements": inserted_movements,
        "movements_per_client": movements_per_client,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed MySQL aislado para benchmark de Cuenta corriente FEMAG."
    )
    parser.add_argument("--clients", type=int, default=2000)
    parser.add_argument("--movements-per-client", type=int, default=100)
    parser.add_argument("--salespeople", type=int, default=20)
    parser.add_argument("--db-name", default="femag_ledger_performance")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra y recrea únicamente la DB de performance. Obligatorio.",
    )
    args = parser.parse_args()

    if not args.reset:
        parser.error("Para sembrar datos debe indicar --reset explicitamente.")

    config = performance_db_config(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.db_name,
    )
    total = args.clients * args.movements_per_client
    print(f"DB performance: {config.user}@{config.host}:{config.port}/{config.database}")
    print(
        f"Seed solicitado: {args.clients:,} clientes, "
        f"{args.salespeople:,} vendedores, {total:,} movimientos"
    )
    print("RESET explicito habilitado: se borrara unicamente la DB de performance.")

    ensure_mysql_database(config, reset=True)
    database = connect_performance_database(config)
    try:
        started = time.perf_counter()
        counts = seed_ledger_data(
            client_count=args.clients,
            movements_per_client=args.movements_per_client,
            salesperson_count=args.salespeople,
        )
        elapsed = time.perf_counter() - started
        print("Seed completado.")
        for key, value in counts.items():
            print(f"  {key}: {value:,}")
        print(f"Tiempo seed: {elapsed:.2f} s")
        print("")
        print("Benchmark sugerido:")
        print(
            "  py scripts/benchmark_ledger_performance_mysql.py "
            f"--db-name {config.database} --assert-thresholds"
        )
    finally:
        if not database.is_closed():
            database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

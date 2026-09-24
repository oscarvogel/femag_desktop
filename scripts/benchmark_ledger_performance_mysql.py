from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Salesperson
from app.services.ledger_query_service import client_portfolio_rows
from scripts.performance_mysql_common import (
    connect_performance_database,
    performance_db_config,
)


@contextmanager
def _count_queries(database):
    original = database.execute_sql
    counter = {"count": 0}

    def counted(*args, **kwargs):
        counter["count"] += 1
        return original(*args, **kwargs)

    database.execute_sql = counted
    try:
        yield counter
    finally:
        database.execute_sql = original


def _measure(database, label: str, callback):
    started = time.perf_counter()
    with _count_queries(database) as counter:
        value = callback()
    elapsed = time.perf_counter() - started
    result = {
        "label": label,
        "seconds": round(elapsed, 4),
        "queries": counter["count"],
    }
    print(f"{label:<38} {elapsed:>8.3f} s   SQL: {counter['count']}")
    return result, value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark MySQL de Cuenta corriente y filtro por vendedor."
    )
    parser.add_argument("--db-name", default="femag_ledger_performance")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--assert-thresholds", action="store_true")
    parser.add_argument("--max-snapshot-seconds", type=float, default=2.0)
    parser.add_argument("--max-open-seconds", type=float, default=3.0)
    parser.add_argument("--max-filter-seconds", type=float, default=0.5)
    args = parser.parse_args()

    if not args.visible:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    config = performance_db_config(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.db_name,
    )
    database = connect_performance_database(config)
    try:
        client_count = Client.select().count()
        movement_count = ClientAccountMovement.select().count()
        salesperson_count = Salesperson.select().count()
        if not client_count or not movement_count:
            raise RuntimeError(
                "La DB de performance no tiene datos. Ejecute primero "
                "seed_ledger_performance_mysql.py --reset."
            )

        print("=" * 78)
        print("FEMAG LEDGER PERFORMANCE BENCHMARK #551")
        print(f"DB: {config.host}:{config.port}/{config.database}")
        print(
            f"Clientes: {client_count:,} | Vendedores: {salesperson_count:,} | "
            f"Movimientos: {movement_count:,}"
        )
        print("=" * 78)

        results: list[dict] = []

        snapshot_result, snapshot = _measure(
            database,
            "client_portfolio_rows snapshot",
            client_portfolio_rows,
        )
        results.append(snapshot_result)
        print(f"  filas cartera: {len(snapshot):,}")

        from PyQt5.QtWidgets import QApplication
        from app.ui.customer_ledger import CustomerLedgerPage

        app = QApplication.instance() or QApplication([])
        open_result, page = _measure(
            database,
            "CustomerLedgerPage constructor",
            lambda: CustomerLedgerPage(current_user="performance"),
        )
        results.append(open_result)
        app.processEvents()

        salesperson = Salesperson.select().order_by(Salesperson.id).first()
        if salesperson is None:
            raise RuntimeError("No hay vendedores para medir el filtro.")
        salesperson_index = page.salesperson_filter.findData(salesperson.id)
        if salesperson_index < 0:
            raise RuntimeError("El vendedor de benchmark no aparece en el filtro.")

        page.salesperson_filter.setCurrentIndex(salesperson_index)
        filter_result, _ = _measure(
            database,
            "Filtro vendedor sobre snapshot",
            lambda: page._on_salesperson_changed(),
        )
        results.append(filter_result)
        app.processEvents()
        print(f"  filas visibles vendedor: {page.clients_table.rowCount():,}")

        all_index = page.salesperson_filter.findData("all")
        page.salesperson_filter.setCurrentIndex(all_index)
        all_filter_result, _ = _measure(
            database,
            "Filtro Todos sobre snapshot",
            lambda: page._on_salesperson_changed(),
        )
        results.append(all_filter_result)
        app.processEvents()

        page.close()
        page.deleteLater()
        app.processEvents()

        failures: list[str] = []
        if snapshot_result["queries"] != 1:
            failures.append(
                f"snapshot ejecuto {snapshot_result['queries']} SQL; se esperaba 1"
            )
        if filter_result["queries"] != 0 or all_filter_result["queries"] != 0:
            failures.append("cambiar vendedor/Todos volvio a consultar MySQL")

        if args.assert_thresholds:
            if snapshot_result["seconds"] > args.max_snapshot_seconds:
                failures.append(
                    f"snapshot {snapshot_result['seconds']:.3f}s > "
                    f"{args.max_snapshot_seconds:.3f}s"
                )
            if open_result["seconds"] > args.max_open_seconds:
                failures.append(
                    f"apertura {open_result['seconds']:.3f}s > "
                    f"{args.max_open_seconds:.3f}s"
                )
            if filter_result["seconds"] > args.max_filter_seconds:
                failures.append(
                    f"filtro vendedor {filter_result['seconds']:.3f}s > "
                    f"{args.max_filter_seconds:.3f}s"
                )

        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "database": config.database,
            "host": config.host,
            "clients": client_count,
            "salespeople": salesperson_count,
            "movements": movement_count,
            "results": results,
            "thresholds": {
                "enabled": args.assert_thresholds,
                "max_snapshot_seconds": args.max_snapshot_seconds,
                "max_open_seconds": args.max_open_seconds,
                "max_filter_seconds": args.max_filter_seconds,
            },
            "failures": failures,
        }
        path = (
            Path(args.json_out)
            if args.json_out
            else Path("outputs/performance")
            / f"ledger_benchmark_{movement_count}_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Resultado JSON: {path}")

        if failures:
            print("BENCHMARK=FAIL")
            for failure in failures:
                print(f"  - {failure}")
            return 1

        print("BENCHMARK=OK")
        return 0
    finally:
        if not database.is_closed():
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())

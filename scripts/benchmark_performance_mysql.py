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

from app.models.load_orders import LoadOrder
from app.models.security import User
from app.services.load_order_service import LoadOrderService
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
    result = {"label": label, "seconds": round(elapsed, 4), "queries": counter["count"]}
    print(f"{label:<34} {elapsed:>8.3f} s   SQL: {counter['count']}")
    return result, value


def _rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return round(psutil.Process().memory_info().rss / (1024 * 1024), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark MySQL FEMAG #491.")
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--visible", action="store_true")
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

    connect_started = time.perf_counter()
    database = connect_performance_database(config)
    connect_seconds = time.perf_counter() - connect_started

    try:
        total_orders = LoadOrder.select().count()
        user = User.get_or_none(User.username == "performance")
        if user is None:
            raise RuntimeError("Falta usuario performance. Ejecute primero el seed.")

        print("=" * 72)
        print("FEMAG PERFORMANCE BENCHMARK #491")
        print(f"DB: {config.host}:{config.port}/{config.database}")
        print(f"Ordenes: {total_orders}")
        print(f"Conexion + schema: {connect_seconds:.3f} s")
        print("=" * 72)

        from app.ui.dashboard import DashboardService

        results = [
            {
                "label": "connection_and_schema",
                "seconds": round(connect_seconds, 4),
                "queries": None,
            }
        ]

        result, _ = _measure(
            database,
            "DashboardService.view_spec",
            lambda: DashboardService().view_spec(demo_mode=False),
        )
        results.append(result)

        service = LoadOrderService(current_user="performance")
        result, orders = _measure(
            database,
            "LoadOrderService.list_orders ALL",
            lambda: service.list_orders(),
        )
        results.append(result)
        print(f"  filas devueltas: {len(orders)}")

        result, limited = _measure(
            database,
            "LoadOrderService.list_orders 100",
            lambda: service.list_orders(limit=100),
        )
        results.append(result)
        print(f"  filas devueltas: {len(limited)}")

        from PyQt5.QtWidgets import QApplication
        from app.ui.desktop_app import FemagDesktopWindow

        app = QApplication.instance() or QApplication([])
        result, window = _measure(
            database,
            "FemagDesktopWindow constructor",
            lambda: FemagDesktopWindow(user=user, demo_mode=False),
        )
        results.append(result)
        app.processEvents()

        rss = _rss_mb()
        if rss is not None:
            print(f"RSS proceso: {rss:.2f} MB")

        window.close()
        app.processEvents()

        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "database": config.database,
            "host": config.host,
            "orders": total_orders,
            "rss_mb": rss,
            "results": results,
        }

        path = (
            Path(args.json_out)
            if args.json_out
            else Path("outputs/performance")
            / f"benchmark_{total_orders}_{datetime.now():%Y%m%d_%H%M%S}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Resultado JSON: {path}")
        return 0
    finally:
        if not database.is_closed():
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())

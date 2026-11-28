"""Agente de sincronizacion de fabrica (#804).

Uso previsto: tarea programada de Windows Server 2019. En esta rebanada
publica un snapshot completo de ordenes; los eventos incrementales y la
aplicacion de lote/fecha llegan en las siguientes rebanadas.

Ejemplos:

- ``python -m app.jobs.sync_agent --snapshot``
- ``python -m app.jobs.sync_agent --status``
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

from app.config.database import initialize_runtime_database
from app.config.schema import (
    ensure_runtime_schema,
    ensure_sync_schema,
    validate_sync_schema,
)
from app.services.exchange_rate_update_service import (
    run_daily_update,
    should_run_daily,
)
from app.services.exchange_rate_providers import (
    BNA_RATE_TYPE,
    BnaProvider,
    UrllibHttpClient,
)
from app.services.exchange_rate_service import ExchangeRateService
from app.services.managerial_repurchase_publisher import (
    ManagerialRepurchasePublisher,
)
from app.services.managerial_snapshot_publisher import (
    ManagerialSnapshotPublisher,
)
from app.services.sync_event_consumer import SyncEventConsumer
from app.services.sync_http_client import SyncHttpClient
from app.services.sync_order_publisher import SyncOrderPublisher
from app.services.sync_service import SyncService

DEFAULT_SYNC_ENV = Path(r"C:\ProgramData\FEMAG\sync.env")
logger = logging.getLogger(__name__)


def _load_config() -> Path | None:
    """Carga sync.env antes de leer la base y las variables de sync."""
    configured = os.getenv("FEMAG_SYNC_ENV_FILE", "").strip()
    path = Path(configured) if configured else DEFAULT_SYNC_ENV
    if not path.is_file():
        if configured:
            raise SystemExit(f"No existe el archivo de configuración {path}.")
        return None
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
    except ImportError:
        pass
    os.environ.setdefault("FEMAG_ENV_FILE", str(path))
    return path


def _configure_logging() -> None:
    log_file = os.getenv("FEMAG_SYNC_LOG_FILE", "").strip()
    handlers = [logging.FileHandler(log_file, encoding="utf-8")] if log_file else None
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _client_from_env() -> SyncHttpClient:
    base_url = os.getenv("FEMAG_SYNC_BASE_URL", "").strip()
    token = os.getenv("FEMAG_SYNC_API_TOKEN", "").strip()
    if not base_url:
        raise SystemExit("Falta FEMAG_SYNC_BASE_URL.")
    if not token:
        raise SystemExit("Falta FEMAG_SYNC_API_TOKEN.")
    try:
        timeout = int(os.getenv("FEMAG_SYNC_TIMEOUT", "90"))
    except ValueError:
        timeout = 90
    return SyncHttpClient(
        base_url,
        token,
        timeout=timeout,
        ca_file=os.getenv("FEMAG_SYNC_CA_FILE", "").strip() or None,
    )


def run_init_schema() -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        # El agente tambien migra las columnas de lote/fecha por contenido:
        # la fabrica puede tener instalada una version anterior del escritorio.
        ensure_runtime_schema(database)
        ensure_sync_schema(database)
        validate_sync_schema(database)
        print("Esquema de sincronizacion listo.")
        return 0
    finally:
        if not database.is_closed():
            database.close()


def run_snapshot(limit: int | None = None) -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        client = _client_from_env()
        publisher = SyncOrderPublisher(limit=limit)
        result = publisher.publish_snapshot(client)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not result["skipped"] else 1
    finally:
        if not database.is_closed():
            database.close()


def run_sync(limit: int | None = None) -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        client = _client_from_env()
        inbound = SyncEventConsumer(client).pull_and_apply()
        publisher = SyncOrderPublisher(limit=limit)
        snapshot = publisher.publish_snapshot(client)
        rates = None
        try:
            if should_run_daily():
                rates = run_daily_update()
        except Exception as exc:
            logger.warning(
                "No se pudieron actualizar las cotizaciones: %s", exc
            )
        managerial = None
        managerial_publisher = ManagerialSnapshotPublisher()
        if managerial_publisher.should_publish():
            try:
                managerial = managerial_publisher.publish(client)
            except Exception as exc:
                logger.warning(
                    "No se pudo publicar el snapshot gerencial: %s", exc
                )
        repurchase = None
        repurchase_publisher = ManagerialRepurchasePublisher()
        if repurchase_publisher.should_publish():
            try:
                repurchase = repurchase_publisher.publish(client)
            except Exception as exc:
                logger.warning(
                    "No se pudo publicar el snapshot de recompra: %s", exc
                )
        managerial_history = None
        if managerial_publisher.should_publish_history():
            try:
                managerial_history = managerial_publisher.publish_history(client)
            except Exception as exc:
                logger.warning(
                    "No se pudo publicar la historia gerencial: %s", exc
                )
        repurchase_history = None
        if repurchase_publisher.should_publish_history():
            try:
                repurchase_history = repurchase_publisher.publish_history(client)
            except Exception as exc:
                logger.warning(
                    "No se pudo publicar la historia de recompra: %s", exc
                )
        print(
            json.dumps(
                {
                    "inbound": inbound,
                    "snapshot": snapshot,
                    "rates": rates.as_dict() if rates is not None else None,
                    "managerial": managerial,
                    "repurchase": repurchase,
                    "managerial_history": managerial_history,
                    "repurchase_history": repurchase_history,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not snapshot["skipped"] else 1
    finally:
        if not database.is_closed():
            database.close()


def run_managerial() -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        client = _client_from_env()
        managerial_publisher = ManagerialSnapshotPublisher()
        repurchase_publisher = ManagerialRepurchasePublisher()
        managerial = managerial_publisher.publish(client)
        repurchase = repurchase_publisher.publish(client)
        managerial_history = managerial_publisher.publish_history(client)
        repurchase_history = repurchase_publisher.publish_history(client)
        print(
            json.dumps(
                {
                    "managerial": managerial,
                    "repurchase": repurchase,
                    "managerial_history": managerial_history,
                    "repurchase_history": repurchase_history,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        if not database.is_closed():
            database.close()


def run_rates() -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        result = run_daily_update(use_lock=True)
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        return 0 if not result.errors else 1
    finally:
        if not database.is_closed():
            database.close()


def run_backfill_bna(start: date, end: date) -> int:
    """Completa BNA historico dia por dia para un rango de fechas."""
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        provider = BnaProvider(
            UrllibHttpClient(),
            lookback_days=max(1, (end - start).days + 1),
        )
        outcome = provider.fetch_series(
            base_currency="USD",
            rate_type=BNA_RATE_TYPE,
            start_date=start,
            end_date=end,
        )
        service = ExchangeRateService("sistema")
        created = unchanged = failed = 0
        errors = list(outcome.errors)
        for rate in outcome.rates:
            try:
                registration = service.register(
                    base_currency=rate.base_currency,
                    quote_currency=rate.quote_currency,
                    effective_date=rate.effective_date,
                    rate_type=rate.rate_type,
                    buy_rate=rate.buy_rate,
                    sell_rate=rate.sell_rate,
                    source=rate.source,
                    origin=rate.origin,
                    fetched_at=rate.fetched_at,
                    created_by="sistema",
                )
            except Exception as exc:  # noqa: BLE001 - seguir con las demas fechas
                failed += 1
                errors.append(f"{rate.effective_date.isoformat()}: {exc}")
            else:
                if registration.created:
                    created += 1
                else:
                    unchanged += 1
        print(
            json.dumps(
                {
                    "provider": provider.name,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "fetched": len(outcome.rates),
                    "created": created,
                    "unchanged": unchanged,
                    "failed": failed,
                    "errors": errors[:20],
                    "warnings": list(outcome.warnings[:20]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not errors else 1
    finally:
        if not database.is_closed():
            database.close()


def run_status() -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        validate_sync_schema(database)
        print(json.dumps(SyncService.status_summary(), ensure_ascii=False, indent=2))
        return 0
    finally:
        if not database.is_closed():
            database.close()


def main(argv: list[str] | None = None) -> int:
    _load_config()
    _configure_logging()
    logger = logging.getLogger("femag.sync_agent")
    parser = argparse.ArgumentParser(description="Agente de sincronizacion FEMAG.")
    parser.add_argument("--sync", action="store_true", help="Aplicar eventos y publicar snapshot")
    parser.add_argument("--snapshot", action="store_true", help="Publicar snapshot completo")
    parser.add_argument(
        "--managerial",
        action="store_true",
        help="Publicar solo el snapshot gerencial",
    )
    parser.add_argument(
        "--rates",
        action="store_true",
        help="Actualizar cotizaciones y salir",
    )
    parser.add_argument(
        "--backfill-bna",
        action="store_true",
        help="Importar BNA historico para un rango y salir",
    )
    parser.add_argument(
        "--from-date",
        type=date.fromisoformat,
        help="Fecha desde para --backfill-bna (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to-date",
        type=date.fromisoformat,
        help="Fecha hasta para --backfill-bna (YYYY-MM-DD)",
    )
    parser.add_argument("--status", action="store_true", help="Mostrar estado local de sync")
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Crear las tablas de sync (requiere permiso DDL)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limite de ordenes")
    args = parser.parse_args(argv)

    try:
        if args.init_schema:
            return run_init_schema()
        if args.status:
            return run_status()
        if args.backfill_bna:
            if args.from_date is None or args.to_date is None:
                print(
                    "ERROR: indique --from-date y --to-date para --backfill-bna.",
                    file=sys.stderr,
                )
                return 2
            return run_backfill_bna(args.from_date, args.to_date)
        if args.rates:
            return run_rates()
        if args.managerial:
            return run_managerial()
        if args.sync:
            return run_sync(limit=args.limit)
        return run_snapshot(limit=args.limit)
    except SystemExit as exc:
        logger.error("%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        logger.exception("Fallo el agente de sincronizacion")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

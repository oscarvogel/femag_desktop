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
from pathlib import Path

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_sync_schema, validate_sync_schema
from app.services.sync_event_consumer import SyncEventConsumer
from app.services.sync_http_client import SyncHttpClient
from app.services.sync_order_publisher import SyncOrderPublisher
from app.services.sync_service import SyncService

DEFAULT_SYNC_ENV = Path(r"C:\ProgramData\FEMAG\sync.env")


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
    return SyncHttpClient(
        base_url,
        token,
        ca_file=os.getenv("FEMAG_SYNC_CA_FILE", "").strip() or None,
    )


def run_init_schema() -> int:
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
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
        print(
            json.dumps(
                {"inbound": inbound, "snapshot": snapshot},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not snapshot["skipped"] else 1
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

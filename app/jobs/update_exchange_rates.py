"""Job central de actualizacion de cotizaciones (#969).

Uso manual:

    python -m app.jobs.update_exchange_rates
    python -m app.jobs.update_exchange_rates --json
    python -m app.jobs.update_exchange_rates --status

No abre FEMAG Desktop ni requiere PyQt. Los errores de red se registran y el
job termina con un codigo controlado; las cotizaciones existentes no se tocan.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.config.settings import resolve_effective_connection_settings
from app.models.system import AppParameter
from app.services.exchange_rate_providers import (
    ArgentinaDatosProvider,
    BnaProvider,
    DolarApiProvider,
    UrllibHttpClient,
)
from app.services.exchange_rate_update_service import (
    DEFAULT_LOOKBACK_DAYS,
    LAST_ATTEMPT_AT_KEY,
    LAST_ATTEMPT_STATUS_KEY,
    LAST_ERROR_KEY,
    LAST_SUCCESS_AT_KEY,
    LAST_SUCCESS_SUMMARY_KEY,
    MAX_LOOKBACK_DAYS,
    STATUS_DRY_RUN,
    STATUS_ERROR,
    STATUS_LOCKED,
    STATUS_OK,
    STATUS_PARTIAL,
    ExchangeRateUpdateService,
)

DEFAULT_ENV_FILE = Path(r"C:\ProgramData\FEMAG\exchange_rates.env")
PROVIDER_NAMES = ("dolarapi", "bna", "argentinadatos")
logger = logging.getLogger("femag.exchange_rates")


def _load_env_file() -> Path | None:
    configured = os.getenv("FEMAG_EXCHANGE_RATE_ENV_FILE", "").strip()
    path = Path(configured) if configured else DEFAULT_ENV_FILE
    if not path.is_file():
        if configured:
            raise SystemExit(f"No existe el archivo de configuracion {path}.")
        return None
    try:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)
    except ImportError:
        pass
    os.environ.setdefault("FEMAG_ENV_FILE", str(path))
    return path


def _configure_logging(log_file: str | Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    target = str(log_file or "").strip()
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=2 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=os.getenv("FEMAG_EXCHANGE_RATE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _default_log_file() -> Path | None:
    configured = os.getenv("FEMAG_EXCHANGE_RATE_LOG_FILE", "").strip()
    if configured:
        return Path(configured)
    runtime_dir = os.getenv("FEMAG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "logs" / "exchange_rates.log"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FEMAG Desktop" / "logs" / "exchange_rates.log"
    return None


def _http_client() -> UrllibHttpClient:
    try:
        timeout = float(os.getenv("FEMAG_EXCHANGE_RATE_HTTP_TIMEOUT", "15"))
    except ValueError:
        timeout = 15.0
    try:
        retries = int(os.getenv("FEMAG_EXCHANGE_RATE_HTTP_RETRIES", "2"))
    except ValueError:
        retries = 2
    return UrllibHttpClient(timeout=max(1.0, timeout), retries=max(0, retries))


def _build_providers(names: set[str], lookback_days: int):
    client = _http_client()
    live = []
    history = []
    if "dolarapi" in names:
        live.append(DolarApiProvider(client))
    if "bna" in names:
        live.append(BnaProvider(client, lookback_days=max(0, lookback_days)))
    if "argentinadatos" in names:
        history.append(ArgentinaDatosProvider(client))
    return live, history


def _open_database():
    resolve_effective_connection_settings()
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    return database


def _read_status() -> dict[str, str | None]:
    keys = (
        LAST_ATTEMPT_AT_KEY,
        LAST_ATTEMPT_STATUS_KEY,
        LAST_SUCCESS_AT_KEY,
        LAST_SUCCESS_SUMMARY_KEY,
        LAST_ERROR_KEY,
    )
    values: dict[str, str | None] = {key: None for key in keys}
    for row in AppParameter.select().where(AppParameter.key.in_(keys)):
        values[row.key] = row.value
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="femag-cotizaciones",
        description="Actualiza las cotizaciones historicas centrales.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=(
            "Dias hacia atras para recuperar faltantes "
            f"(0..{MAX_LOOKBACK_DAYS}; default {DEFAULT_LOOKBACK_DAYS})."
        ),
    )
    parser.add_argument(
        "--providers",
        default=",".join(PROVIDER_NAMES),
        help=(
            "Proveedores separados por coma: "
            f"{', '.join(PROVIDER_NAMES)}."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Consulta y valida sin escribir cotizaciones ni estado.",
    )
    parser.add_argument(
        "--no-gap",
        action="store_true",
        help="No recupera fechas faltantes recientes.",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Omite el lock entre procesos (solo para diagnostico).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emite el resultado en JSON.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Muestra el estado de la ultima corrida y sale.",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help="Archivo de log. Por defecto usa el runtime de produccion.",
    )
    return parser


def _validate_providers(raw: str) -> set[str]:
    names = {part.strip().lower() for part in str(raw or "").split(",") if part.strip()}
    if not names:
        raise SystemExit("Debe indicar al menos un proveedor.")
    unknown = names - set(PROVIDER_NAMES)
    if unknown:
        raise SystemExit(
            f"Proveedor desconocido: {', '.join(sorted(unknown))}. "
            f"Validos: {', '.join(PROVIDER_NAMES)}."
        )
    return names


def _print_human(result) -> None:
    print(f"Estado: {result.status}")
    if result.locked:
        print("Otra ejecucion esta activa; no se hizo nada.")
        return
    print(
        f"Registradas: {result.registered} | "
        f"Sin cambios: {result.unchanged} | "
        f"Fallidas: {result.failed}"
    )
    for report in result.providers:
        print(
            f"- {report.provider}: {report.status} "
            f"(obtenidas {report.fetched}, nuevas {report.created}, "
            f"sin cambios {report.unchanged}, fallidas {report.failed})"
        )
    for error in result.errors[:10]:
        print(f"  ERROR: {error}")
    for warning in result.warnings[:10]:
        print(f"  AVISO: {warning}")


def _print_status(values: dict[str, str | None], as_json: bool) -> int:
    if as_json:
        print(json.dumps(values, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Ultima corrida: {values.get(LAST_ATTEMPT_AT_KEY) or '-'}")
        print(f"Estado: {values.get(LAST_ATTEMPT_STATUS_KEY) or '-'}")
        print(f"Ultimo exito: {values.get(LAST_SUCCESS_AT_KEY) or '-'}")
        print(f"Ultimo error: {values.get(LAST_ERROR_KEY) or '-'}")
        summary = values.get(LAST_SUCCESS_SUMMARY_KEY)
        if summary:
            print("Resumen ultimo exito:")
            print(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_env_file()
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_file or _default_log_file())
    try:
        database = _open_database()
    except Exception as exc:  # noqa: BLE001 - el job reporta y sale
        logger.exception("No se pudo abrir la base de datos")
        if args.json:
            print(json.dumps({"status": STATUS_ERROR, "error": str(exc)}))
        else:
            print(f"ERROR: no se pudo abrir la base de datos: {exc}")
        return 1
    try:
        if args.status:
            return _print_status(_read_status(), args.json)

        providers = _validate_providers(args.providers)
        lookback = 0 if args.no_gap else max(
            0, min(int(args.lookback_days), MAX_LOOKBACK_DAYS)
        )
        live, history = _build_providers(providers, lookback)
        service = ExchangeRateUpdateService(
            providers=live,
            history_providers=history,
        )
        result = service.run(
            lookback_days=lookback,
            dry_run=args.dry_run,
            use_lock=not args.no_lock,
        )
        logger.info(
            "Cotizaciones: status=%s registered=%s unchanged=%s failed=%s errors=%s warnings=%s",
            result.status,
            result.registered,
            result.unchanged,
            result.failed,
            len(result.errors),
            len(result.warnings),
        )
        for error in result.errors:
            logger.warning("Cotizaciones: %s", error)
        for warning in result.warnings:
            logger.info("Cotizaciones: %s", warning)
        if args.json:
            print(result.to_json())
        else:
            _print_human(result)
        if result.status in {STATUS_OK, STATUS_LOCKED, STATUS_DRY_RUN}:
            return 0
        if result.status == STATUS_PARTIAL:
            return 2
        return 1
    except Exception as exc:  # noqa: BLE001 - tarea programada controlada
        logger.exception("Fallo la actualizacion de cotizaciones")
        if args.json:
            print(json.dumps({"status": STATUS_ERROR, "error": str(exc)}))
        else:
            print(f"ERROR: {exc}")
        return 1
    finally:
        if not database.is_closed():
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI de importacion historica de cotizaciones (#970).

Ejemplos:

    python -m app.jobs.import_historical_exchange_rates --budgets --dry-run
    python -m app.jobs.import_historical_exchange_rates --budgets --types oficial
    python -m app.jobs.import_historical_exchange_rates ^
        --from-date 2026-01-01 --to-date 2026-11-27 --currency USD
    python -m app.jobs.import_historical_exchange_rates --budgets --json

No toca presupuestos: solo lee ``budget.issue_date``. No ejecuta importaciones
masivas de produccion por si solo; el operador define el rango y el limite.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.config.settings import resolve_effective_connection_settings
from app.services.exchange_rate_history_import_service import (
    DEFAULT_MAX_RECORDS,
    DEFAULT_MAX_REQUESTS,
    DEFAULT_SOURCE,
    STATUS_DRY_RUN,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
    HistoricalExchangeRateImportService,
    HistoricalImportError,
)
from app.services.exchange_rate_providers import (
    ArgentinaDatosProvider,
    UrllibHttpClient,
)

logger = logging.getLogger("femag.exchange_rates_history")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Fecha invalida: {value!r}. Use YYYY-MM-DD."
        ) from None


def _parse_types(value: str) -> tuple[str, ...]:
    return tuple(
        part.strip().lower()
        for part in str(value or "").split(",")
        if part.strip()
    )


def _load_holidays(path: str) -> set[date]:
    if not path:
        return set()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    result: set[date] = set()
    for item in payload:
        raw = item.get("fecha") if isinstance(item, dict) else item
        if raw:
            result.add(date.fromisoformat(str(raw)))
    return result


def _configure_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        path = Path(log_file)
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


def _default_log_file() -> str | None:
    configured = os.getenv("FEMAG_EXCHANGE_RATE_LOG_FILE", "").strip()
    if configured:
        return configured
    runtime_dir = os.getenv("FEMAG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return str(Path(runtime_dir) / "logs" / "exchange_rates_history.log")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return str(
            Path(local_app_data)
            / "FEMAG Desktop"
            / "logs"
            / "exchange_rates_history.log"
        )
    return None


def _open_database():
    resolve_effective_connection_settings()
    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    return database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="femag-cotizaciones-historicas",
        description="Importa cotizaciones historicas para los presupuestos.",
    )
    parser.add_argument("--from-date", type=_parse_date, help="Fecha desde (YYYY-MM-DD).")
    parser.add_argument("--to-date", type=_parse_date, help="Fecha hasta (YYYY-MM-DD).")
    parser.add_argument(
        "--budgets",
        action="store_true",
        help="Descubre el rango desde los presupuestos existentes.",
    )
    parser.add_argument("--currency", default="USD", help="Moneda base (default USD).")
    parser.add_argument("--quote", default="ARS", help="Moneda cotizada (default ARS).")
    parser.add_argument(
        "--types",
        default="",
        help="Tipos separados por coma; por defecto todos los del alcance.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help=f"Fuente historica (default {DEFAULT_SOURCE}).",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Revisa correcciones de la misma fuente y crea versiones.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=DEFAULT_MAX_RECORDS,
        help=(
            "Maximo de registros nuevos por corrida; 0 = sin limite "
            f"(default {DEFAULT_MAX_RECORDS})."
        ),
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=f"Maximo de solicitudes HTTP (default {DEFAULT_MAX_REQUESTS}).",
    )
    parser.add_argument(
        "--holidays-file",
        default="",
        help="JSON con feriados ISO para clasificar faltantes.",
    )
    parser.add_argument(
        "--coverage-any-source",
        action="store_true",
        help="Evalua cobertura de presupuestos contra cualquier fuente.",
    )
    parser.add_argument("--json", action="store_true", help="Salida JSON.")
    parser.add_argument("--log-file", default="", help="Archivo de log.")
    return parser


def _print_human(result) -> None:
    print(f"Estado: {result.status}")
    print(
        f"Rango: {result.start_date.isoformat()} -> {result.end_date.isoformat()} | "
        f"{result.base_currency}/{result.quote_currency} | fuente {result.source}"
    )
    print(
        f"Solicitudes: {result.provider_requests} | obtenidas: {result.fetched} | "
        f"importadas: {result.imported} | versiones: {result.new_versions} | "
        f"sin cambios: {result.unchanged} | existentes: {result.existing} | "
        f"omitidas: {result.skipped_existing + result.skipped_other_source} | "
        f"diferidas: {result.deferred}"
    )
    print(
        f"Faltantes reportados: sin publicacion={len(result.missing_publication)} | "
        f"sin cobertura={len(result.missing_coverage)}"
    )
    for report in result.reports:
        print(
            f"- {report.base_currency}/{report.rate_type}: fetched={report.fetched} "
            f"imported={report.imported} versions={report.new_versions} "
            f"unchanged={report.unchanged} skipped={report.skipped_existing} "
            f"other_source={report.skipped_other_source} deferred={report.deferred}"
        )
        for error in report.errors[:5]:
            print(f"    ERROR: {error}")
    if result.budget_audit:
        audit = result.budget_audit
        print(
            f"Presupuestos: {audit.total_budgets} en {audit.distinct_dates} fechas "
            f"({audit.first_date} -> {audit.last_date})"
        )
    for coverage in result.coverage:
        print(
            f"Cobertura {coverage.base_currency}/{coverage.rate_type} "
            f"fuente={coverage.source or 'cualquiera'}: "
            f"exacta={coverage.exact_budgets} anterior={coverage.prior_budgets} "
            f"sin usable={coverage.missing_budgets}"
        )
    for warning in result.warnings[:10]:
        print(f"  AVISO: {warning}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_file or _default_log_file())
    if not args.budgets and not (args.from_date and args.to_date):
        args.budgets = True
    if not args.budgets and not (args.from_date and args.to_date):
        print("ERROR: indique --budgets o --from-date/--to-date.")
        return 1
    if (args.from_date is None) != (args.to_date is None):
        print("ERROR: --from-date y --to-date deben ir juntos.")
        return 1

    try:
        database = _open_database()
    except Exception as exc:  # noqa: BLE001
        logger.exception("No se pudo abrir la base")
        if args.json:
            print(json.dumps({"status": STATUS_ERROR, "error": str(exc)}))
        else:
            print(f"ERROR: no se pudo abrir la base: {exc}")
        return 1

    try:
        holidays = _load_holidays(args.holidays_file)
        provider = ArgentinaDatosProvider(
            UrllibHttpClient(
                timeout=float(os.getenv("FEMAG_EXCHANGE_RATE_HTTP_TIMEOUT", "20")),
                retries=int(os.getenv("FEMAG_EXCHANGE_RATE_HTTP_RETRIES", "2")),
            )
        )
        service = HistoricalExchangeRateImportService(provider=provider)
        rate_types = _parse_types(args.types) or None
        max_records = None if args.max_records == 0 else args.max_records
        def _progress(report):
            logger.info(
                "Progreso %s/%s: fetched=%s imported=%s versions=%s "
                "skipped=%s deferred=%s",
                report.base_currency,
                report.rate_type,
                report.fetched,
                report.imported,
                report.new_versions,
                report.skipped_existing + report.skipped_other_source,
                report.deferred,
            )

        common = {
            "base_currency": args.currency,
            "quote_currency": args.quote,
            "rate_types": rate_types,
            "source": args.source,
            "dry_run": args.dry_run,
            "refresh": args.refresh,
            "max_records": max_records,
            "max_requests": args.max_requests,
            "holidays": holidays,
            "on_progress": _progress,
        }
        if args.budgets:
            result = service.import_for_budgets(**common)
        else:
            result = service.import_range(
                start_date=args.from_date,
                end_date=args.to_date,
                **common,
            )
        if args.coverage_any_source and result.budget_audit:
            coverage = tuple(
                service.coverage(
                    base_currency=result.base_currency,
                    quote_currency=result.quote_currency,
                    rate_type=rate_type,
                    source=None,
                    budget_audit=result.budget_audit,
                )
                for rate_type in result.rate_types
            )
            result = dataclasses.replace(result, coverage=coverage)

        logger.info(
            "Historicas: status=%s imported=%s versions=%s unchanged=%s "
            "deferred=%s errors=%s",
            result.status,
            result.imported,
            result.new_versions,
            result.unchanged,
            result.deferred,
            len(result.errors),
        )
        if args.json:
            print(result.to_json())
        else:
            _print_human(result)
        if result.status in {STATUS_OK, STATUS_DRY_RUN}:
            return 0
        if result.status == STATUS_PARTIAL:
            return 2
        return 1
    except (HistoricalImportError, ValueError) as exc:
        logger.error("Importacion historica rechazada: %s", exc)
        if args.json:
            print(json.dumps({"status": STATUS_ERROR, "error": str(exc)}))
        else:
            print(f"ERROR: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fallo la importacion historica")
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

"""Actualizacion diaria centralizada de cotizaciones (#969).

Orquesta proveedores HTTP, recupera faltantes recientes y persiste con el
``ExchangeRateService`` de #968. No abre transacciones durante las consultas
HTTP: primero obtiene, despues registra cada cotizacion en una transaccion
corta.

El job es independiente del escritorio: se ejecuta desde linea de comandos o
desde el Programador de tareas de Windows.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

from peewee import IntegrityError

from app.models.exchange_rates import ExchangeRate
from app.models.system import AppParameter
from app.services.exchange_rate_providers import (
    BNA_RATE_TYPE,
    USD_RATE_TYPES,
    ArgentinaDatosProvider,
    BnaProvider,
    DolarApiProvider,
    ExchangeRateProvider,
    HttpClient,
    ProviderError,
    ProviderOutcome,
    RateGap,
    UrllibHttpClient,
    ZONA_AR,
)
from app.services.exchange_rate_service import (
    ExchangeRateError,
    ExchangeRateService,
)

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_ERROR = "error"
STATUS_LOCKED = "locked"
STATUS_DRY_RUN = "dry_run"

DEFAULT_LOOKBACK_DAYS = 7
MAX_LOOKBACK_DAYS = 31
DAILY_UPDATE_HOUR_ART = 19
DAILY_RETRY_MINUTES = 30
DEFAULT_LOCK_STALE_SECONDS = 2 * 60 * 60
MAX_SERIALIZED_ITEMS = 20

LAST_ATTEMPT_AT_KEY = "exchange_rate.last_attempt_at"
LAST_ATTEMPT_STATUS_KEY = "exchange_rate.last_attempt_status"
LAST_SUCCESS_AT_KEY = "exchange_rate.last_success_at"
LAST_SUCCESS_SUMMARY_KEY = "exchange_rate.last_success_summary"
LAST_ERROR_KEY = "exchange_rate.last_error"

HISTORY_TYPES: tuple[tuple[str, str], ...] = tuple(
    ("USD", rate_type) for rate_type in USD_RATE_TYPES
) + (("BRL", "oficial"),)


@dataclass(frozen=True)
class ProviderReport:
    provider: str
    status: str
    fetched: int
    created: int
    unchanged: int
    failed: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "status": self.status,
            "fetched": self.fetched,
            "created": self.created,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ExchangeRateUpdateResult:
    status: str
    started_at: datetime
    finished_at: datetime
    today: date
    registered: int = 0
    unchanged: int = 0
    failed: int = 0
    providers: tuple[ProviderReport, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    locked: bool = False
    dry_run: bool = False

    @property
    def has_data(self) -> bool:
        return self.registered + self.unchanged > 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "locked": self.locked,
            "dry_run": self.dry_run,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "today": self.today.isoformat(),
            "registered": self.registered,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "providers": [report.as_dict() for report in self.providers],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)


def _pid_alive(pid: int) -> bool:
    """Comprueba un PID sin dependencias externas. Best effort."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not process:
                return False
            ctypes.windll.kernel32.CloseHandle(process)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class FileJobLock:
    """Lock entre procesos basado en creacion atomica de archivo.

    Si el proceso duenio murio o el archivo supero ``stale_seconds``, el lock
    se considera abandonado y se recupera. No se apoya en locks del sistema
    operativo para poder funcionar igual en Windows y en tests POSIX.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        stale_seconds: int = DEFAULT_LOCK_STALE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ):
        self.path = Path(path) if path else default_lock_path()
        self.stale_seconds = max(1, int(stale_seconds))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._owned = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                if attempt == 0 and self._is_stale():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        return False
                    continue
                return False
            try:
                payload = json.dumps(
                    {
                        "pid": os.getpid(),
                        "started_at": self.clock().astimezone(timezone.utc).isoformat(),
                    }
                ).encode("utf-8")
                os.write(descriptor, payload)
            finally:
                os.close(descriptor)
            self._owned = True
            return True
        return False

    def release(self) -> None:
        if not self._owned:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("No se pudo borrar el lock %s", self.path)
        finally:
            self._owned = False

    def _is_stale(self) -> bool:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return True
        age = self.clock().timestamp() - stat.st_mtime
        if age > self.stale_seconds:
            return True
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid") or 0)
        except (OSError, ValueError, TypeError):
            return False
        return bool(pid and not _pid_alive(pid))

    def __enter__(self) -> "FileJobLock":
        if not self.acquire():
            raise RuntimeError(f"El lock {self.path} ya esta tomado.")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def default_lock_path() -> Path:
    configured = os.getenv("FEMAG_EXCHANGE_RATE_LOCK", "").strip()
    if configured:
        return Path(configured)
    runtime_dir = os.getenv("FEMAG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "exchange_rate_update.lock"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FEMAG Desktop" / "exchange_rate_update.lock"
    return Path(tempfile.gettempdir()) / "femag_exchange_rate_update.lock"


class ExchangeRateUpdateService:
    """Junta proveedores, faltantes, persistencia y estado de la ultima corrida."""

    def __init__(
        self,
        *,
        current_user: str = "sistema",
        http_client: HttpClient | None = None,
        providers: Sequence[ExchangeRateProvider] | None = None,
        history_providers: Sequence[ExchangeRateProvider] | None = None,
        lock_path: Path | str | None = None,
        lock_stale_seconds: int = DEFAULT_LOCK_STALE_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ):
        self.current_user = current_user
        client = http_client or UrllibHttpClient()
        self.providers = list(
            providers
            if providers is not None
            else [DolarApiProvider(client), BnaProvider(client)]
        )
        self.history_providers = list(
            history_providers
            if history_providers is not None
            else [ArgentinaDatosProvider(client)]
        )
        self.lock_path = lock_path
        self.lock_stale_seconds = lock_stale_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        today: date | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        dry_run: bool = False,
        use_lock: bool = True,
    ) -> ExchangeRateUpdateResult:
        started_at = self.clock().astimezone(timezone.utc)
        today = today or started_at.astimezone(ZONA_AR).date()
        lookback = max(0, min(int(lookback_days), MAX_LOOKBACK_DAYS))
        lock = (
            FileJobLock(
                self.lock_path,
                stale_seconds=self.lock_stale_seconds,
                clock=self.clock,
            )
            if use_lock
            else None
        )
        if lock is not None and not lock.acquire():
            finished_at = self.clock().astimezone(timezone.utc)
            return ExchangeRateUpdateResult(
                status=STATUS_LOCKED,
                started_at=started_at,
                finished_at=finished_at,
                today=today,
                locked=True,
                dry_run=dry_run,
            )

        try:
            result = self._run_locked(
                today=today,
                lookback_days=lookback,
                dry_run=dry_run,
                started_at=started_at,
            )
        finally:
            if lock is not None:
                lock.release()
        if not dry_run:
            self._record_status(result)
        return result

    def _run_locked(
        self,
        *,
        today: date,
        lookback_days: int,
        dry_run: bool,
        started_at: datetime,
    ) -> ExchangeRateUpdateResult:
        missing_bna = (
            self._missing_gaps(
                today=today,
                lookback_days=lookback_days,
                types=(("USD", BNA_RATE_TYPE), ("BRL", BNA_RATE_TYPE)),
            )
            if lookback_days > 0
            else frozenset()
        )

        reports: list[ProviderReport] = []
        all_errors: list[str] = []
        all_warnings: list[str] = []
        registered = unchanged = failed = 0

        phase_one = self._collect(self.providers, today=today, missing=missing_bna)
        for outcome in phase_one:
            report, counts = self._persist_outcome(outcome, dry_run=dry_run)
            reports.append(report)
            all_errors.extend(report.errors)
            all_warnings.extend(report.warnings)
            registered += counts[0]
            unchanged += counts[1]
            failed += counts[2]

        missing_history = (
            self._missing_gaps(
                today=today,
                lookback_days=lookback_days,
                types=HISTORY_TYPES,
            )
            if lookback_days > 0 and self.history_providers
            else frozenset()
        )
        phase_two = self._collect(
            self.history_providers, today=today, missing=missing_history
        )
        for outcome in phase_two:
            report, counts = self._persist_outcome(outcome, dry_run=dry_run)
            reports.append(report)
            all_errors.extend(report.errors)
            all_warnings.extend(report.warnings)
            registered += counts[0]
            unchanged += counts[1]
            failed += counts[2]

        if dry_run:
            status = STATUS_DRY_RUN if not all_errors else STATUS_PARTIAL
        elif failed == 0 and not all_errors:
            status = STATUS_OK
        elif registered + unchanged > 0:
            status = STATUS_PARTIAL
        else:
            status = STATUS_ERROR

        return ExchangeRateUpdateResult(
            status=status,
            started_at=started_at,
            finished_at=self.clock().astimezone(timezone.utc),
            today=today,
            registered=registered,
            unchanged=unchanged,
            failed=failed,
            providers=tuple(reports),
            errors=tuple(all_errors),
            warnings=tuple(all_warnings),
            dry_run=dry_run,
        )

    def _collect(
        self,
        providers: Sequence[ExchangeRateProvider],
        *,
        today: date,
        missing: frozenset[RateGap],
    ) -> list[ProviderOutcome]:
        outcomes: list[ProviderOutcome] = []
        for provider in providers:
            name = getattr(provider, "name", type(provider).__name__)
            try:
                outcome = provider.fetch(today=today, missing=missing)
            except ProviderError as exc:
                logger.warning("Proveedor %s fallo: %s", name, exc)
                outcomes.append(
                    ProviderOutcome(provider=name, errors=(str(exc),))
                )
            except Exception as exc:  # noqa: BLE001 - el job debe seguir
                logger.exception("Proveedor %s fallo de forma inesperada", name)
                outcomes.append(
                    ProviderOutcome(
                        provider=name,
                        errors=(f"{type(exc).__name__}: {exc}",),
                    )
                )
            else:
                outcomes.append(outcome)
        return outcomes

    def _persist_outcome(
        self,
        outcome: ProviderOutcome,
        *,
        dry_run: bool,
    ) -> tuple[ProviderReport, tuple[int, int, int]]:
        errors = list(outcome.errors)
        warnings = list(outcome.warnings)
        created = unchanged = failed = 0
        if dry_run:
            created = unchanged = 0
        else:
            service = ExchangeRateService(self.current_user)
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
                        created_by=self.current_user,
                    )
                except ExchangeRateError as exc:
                    failed += 1
                    errors.append(
                        f"{outcome.provider} {rate.base_currency}/"
                        f"{rate.quote_currency} {rate.rate_type} "
                        f"{rate.effective_date.isoformat()}: {exc}"
                    )
                else:
                    if registration.created:
                        created += 1
                    else:
                        unchanged += 1

        if errors and (outcome.rates or created or unchanged):
            status = STATUS_PARTIAL
        elif errors:
            status = STATUS_ERROR
        elif not outcome.rates:
            status = "sin_datos"
        else:
            status = STATUS_OK
        report = ProviderReport(
            provider=outcome.provider,
            status=status,
            fetched=len(outcome.rates),
            created=created,
            unchanged=unchanged,
            failed=failed,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        return report, (created, unchanged, failed)

    def _missing_gaps(
        self,
        *,
        today: date,
        lookback_days: int,
        types: Iterable[tuple[str, str]],
    ) -> frozenset[RateGap]:
        start = today - timedelta(days=lookback_days)
        end = today - timedelta(days=1)
        if end < start:
            return frozenset()
        gaps: set[RateGap] = set()
        for base_currency, rate_type in types:
            existing = {
                row.effective_date
                for row in ExchangeRate.select(ExchangeRate.effective_date).where(
                    (ExchangeRate.base_currency == base_currency)
                    & (ExchangeRate.quote_currency == "ARS")
                    & (ExchangeRate.rate_type == rate_type)
                    & (ExchangeRate.effective_date >= start)
                    & (ExchangeRate.effective_date <= end)
                )
            }
            current = start
            while current <= end:
                if current not in existing:
                    gaps.add(
                        RateGap(
                            base_currency=base_currency,
                            quote_currency="ARS",
                            rate_type=rate_type,
                            effective_date=current,
                        )
                    )
                current += timedelta(days=1)
        return frozenset(gaps)

    def _record_status(self, result: ExchangeRateUpdateResult) -> None:
        attempt_at = result.finished_at.isoformat()
        self._set_parameter(LAST_ATTEMPT_AT_KEY, attempt_at)
        self._set_parameter(LAST_ATTEMPT_STATUS_KEY, result.status)
        summary = {
            "status": result.status,
            "finished_at": attempt_at,
            "today": result.today.isoformat(),
            "registered": result.registered,
            "unchanged": result.unchanged,
            "failed": result.failed,
            "providers": [
                {
                    "provider": report.provider,
                    "status": report.status,
                    "fetched": report.fetched,
                    "created": report.created,
                    "unchanged": report.unchanged,
                    "failed": report.failed,
                }
                for report in result.providers
            ],
            "errors": list(result.errors[:MAX_SERIALIZED_ITEMS]),
            "warnings": list(result.warnings[:MAX_SERIALIZED_ITEMS]),
        }
        if result.status in {STATUS_OK, STATUS_PARTIAL} and result.has_data:
            self._set_parameter(LAST_SUCCESS_AT_KEY, attempt_at)
            self._set_parameter(
                LAST_SUCCESS_SUMMARY_KEY,
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
            )
            self._set_parameter(LAST_ERROR_KEY, "")
        elif result.status == STATUS_ERROR:
            message = "; ".join(result.errors) or "sin datos"
            self._set_parameter(LAST_ERROR_KEY, message[:2000])

    @staticmethod
    def _set_parameter(key: str, value: str) -> None:
        try:
            row, _created = AppParameter.get_or_create(key=key)
        except IntegrityError:
            row = AppParameter.get(AppParameter.key == key)
        row.value = value
        row.save(only=[AppParameter.value])


def _parameter_datetime(key: str) -> datetime | None:
    """Lee una marca de tiempo guardada en ``AppParameter`` sin romper el job."""
    try:
        row = AppParameter.get_or_none(AppParameter.key == key)
    except Exception:  # noqa: BLE001 - tabla ausente o base no preparada
        return None
    if row is None or not row.value:
        return None
    try:
        parsed = datetime.fromisoformat(str(row.value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def should_run_daily(*, now: datetime | None = None) -> bool:
    """Indica si corresponde actualizar cotizaciones en esta corrida.

    La actualizacion corre todos los dias despues de las 19:00 de Argentina.
    Si el servidor estuvo apagado, el primer sync posterior la recupera. Los
    intentos fallidos se reintentan cada 30 minutos para no golpear las APIs
    cada 5 minutos.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    last_attempt = _parameter_datetime(LAST_ATTEMPT_AT_KEY)
    if last_attempt is not None:
        elapsed = (current - last_attempt).total_seconds()
        if elapsed < DAILY_RETRY_MINUTES * 60:
            return False
    last_success = _parameter_datetime(LAST_SUCCESS_AT_KEY)
    if last_success is None:
        return True
    current_art = current.astimezone(ZONA_AR)
    success_art = last_success.astimezone(ZONA_AR)
    if (
        success_art.date() < current_art.date()
        and current_art.hour >= DAILY_UPDATE_HOUR_ART
    ):
        return True
    return (current - last_success).total_seconds() >= 24 * 3600


def run_daily_update(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    use_lock: bool = True,
    now: datetime | None = None,
) -> ExchangeRateUpdateResult:
    """Ejecuta la actualizacion diaria con la conexion ya abierta."""
    client = UrllibHttpClient()
    lookback = max(0, min(int(lookback_days), MAX_LOOKBACK_DAYS))
    service = ExchangeRateUpdateService(
        http_client=client,
        providers=[
            DolarApiProvider(client),
            BnaProvider(client, lookback_days=lookback),
        ],
        history_providers=[ArgentinaDatosProvider(client)],
    )
    today = now.astimezone(ZONA_AR).date() if now is not None else None
    return service.run(
        today=today,
        lookback_days=lookback,
        use_lock=use_lock,
    )

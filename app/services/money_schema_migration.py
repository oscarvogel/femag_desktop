"""Tarea de actualización: migración de columnas monetarias FLOAT -> DECIMAL.

Por qué vive acá y no en ``scripts/``
-------------------------------------

La aplicación de producción es un EXE congelado de PyInstaller: en el servidor
**no hay Python ni el repositorio**. Una tarea que deba ejecutarse durante la
actualización, sin que el operador toque nada, tiene que vivir en ``app/`` para
viajar dentro del binario.

Cuándo corre
------------

La ejecuta :func:`ensure_money_schema_migrated`, que se invoca desde
``app/production_entrypoint.py::run()`` **antes** de abrir la interfaz. Es un
bloqueo de arranque: si la migración no puede completarse, FEMAG no abre para
operar.

Es exactamente una vez, y de forma segura:

* **El estado del esquema es la autoridad**, no un flag. Si quedan columnas
  pendientes, se migra; si no, no se hace nada. Así el sistema es idempotente
  por construcción: aunque se borre el recibo, o la migración haya quedado a
  medias, volver a abrir completa el trabajo.
* El recibo en disco existe para **auditoría**, no comon de ejecución.
* El precheck corre siempre antes de alterar. Si algún valor no entra en
  DECIMAL(18,2), la migración **aborta** y no se toca ninguna columna.

Qué NO hace
-----------

**No repara documentos históricos.** La migración de esquema y la reparación de
presupuestos son dos cosas distintas. Acá no se modifica ningún ``Budget`` ni
ningún ``ClientAccountMovement`` de tipo documento: sólo el tipo de la columna.
Si quedan inconsistencias históricas, se informa cuántas son y se deja la
decisión al operador.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config.money_columns import (
    MONEY_COLUMNS,
    MoneyMigrationAbort,
    migrate_money_columns_to_decimal,
    precheck_money_columns,
)
from app.services.mysql_dump import DatabaseDump, safe_database_filename

#: Receipt file name under ``%LOCALAPPDATA%\FEMAG Desktop\logs``.
RECEIPT_NAME = "money_schema_migration.json"

TASK_VERSION = 1

STATUS_OK = "ok"
STATUS_ABORTED = "aborted"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class MoneyMigrationReport:
    """Resultado de la tarea, pensado para log y para el mensaje al operador."""

    status: str
    database: str = ""
    host: str = ""
    user: str = ""
    columns_registered: int = len(MONEY_COLUMNS)
    columns_pending_before: int = 0
    columns_altered: int = 0
    columns_pending_after: int = 0
    columns_exact_decimal: int = 0
    values_out_of_range: int = 0
    values_to_quantize: int = 0
    backup_path: str | None = None
    backup_message: str | None = None
    historical_mismatches: int | None = None
    historical_critical: int | None = None
    historical_potential: str | None = None
    message: str | None = None
    receipt_path: str | None = None
    steps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_SKIPPED)

    def as_dict(self) -> dict:
        data = dict(self.__dict__)
        data.pop("steps", None)
        return data

    def summary_lines(self) -> list[str]:
        """Líneas para el log y para el mensaje final al operador."""
        lineas = [
            f"money-schema-migration status={self.status}",
            f"  database: {self.database or '-'} host={self.host or '-'} user={self.user or '-'}",
            f"  columns registered: {self.columns_registered}",
            f"  columns pending before: {self.columns_pending_before}",
            f"  columns altered: {self.columns_altered}",
            f"  columns pending after: {self.columns_pending_after}",
            f"  columns DECIMAL(18,2) exact: {self.columns_exact_decimal}/{self.columns_registered}",
            f"  values out of range: {self.values_out_of_range}",
            f"  values to quantize: {self.values_to_quantize}",
        ]
        if self.backup_path:
            lineas.append(f"  backup: {self.backup_path}")
        if self.receipt_path:
            lineas.append(f"  receipt: {self.receipt_path}")
        if self.historical_mismatches is not None:
            lineas.append(
                f"  historical header mismatches: {self.historical_mismatches} "
                f"(NO reparados automaticamente)"
            )
            lineas.append(f"  historical critical cases: {self.historical_critical}")
            lineas.append(
                f"  potential financial difference: ${self.historical_potential}"
            )
        if self.message:
            lineas.append(f"  message: {self.message}")
        return lineas


def receipt_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "logs" / RECEIPT_NAME


def _read_receipt(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_receipt(path: Path, report: MoneyMigrationReport, version: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "money_columns_float_to_decimal",
        "task_version": TASK_VERSION,
        "build_version": version,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **report.as_dict(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _open_writable(target):
    """Abre la base escribible y **enlaza el proxy de modelos**.

    El enlace no es opcional. Todos los modelos de FEMAG declaran
    ``Meta.database = database_proxy`` (``app/models/base.py``), así que cualquier
    consulta por modelos sin proxy inicializado lanza
    ``AttributeError: Cannot use uninitialized Proxy``. Esto pasaba porque la
    tarea corre antes de que ``main()`` inicialice la base.

    Enlazar aquí además garantiza una sola conexión para toda la tarea: el SQL
    crudo del precheck, los ALTER y el conteo de históricos usan el mismo objeto.

    Deliberadamente NO se usa ``FemagMySQLDatabase``: su ``connect()`` corre la
    preparación idempotente del esquema. Esta tarea ya controla el orden.
    """
    from peewee import MySQLDatabase

    from app.config.database import bind_database, resolve_mysql_host_ipv4

    database = MySQLDatabase(
        target.database,
        host=resolve_mysql_host_ipv4(target.host),
        port=target.port,
        user=target.user,
        password=target.password,
        charset="utf8mb4",
    )
    # Orden correcto: primero el proxy, después la conexión.
    bind_database(database)
    database.connect(reuse_if_open=True)
    return database


def _make_backup(target, runtime_dir: Path) -> DatabaseDump:
    """Respaldo de la base antes de alterar. Usa el dump puro Python.

    No se depende de ``mysqldump``: en el servidor puede no existir el cliente
    MySQL. El dump puro Python ya existe en el proyecto y publica el archivo de
    forma atómica.
    """
    from app.config.secure_credentials import (
        RuntimeConnection,
        load_runtime_connection,
    )
    from app.services.mysql_dump import dump_database_with_python

    connection = load_runtime_connection()
    if (
        connection.database != target.database
        or connection.host != target.host
        or int(connection.port) != int(target.port)
    ):
        # La credencial guardada apunta a otra base: no se respalda la equivocada.
        connection = RuntimeConnection(
            host=target.host,
            port=int(target.port),
            database=target.database,
            user=target.user,
            password=target.password,
        )

    destino = (
        Path(runtime_dir)
        / "backups"
        / "pre-money-schema"
        / f"{safe_database_filename(target.database)}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    return dump_database_with_python(connection, target.database, destino)


def _count_out_of_range(database) -> int:
    """Cuántos valores no entran en el DECIMAL destino. Sólo lectura."""
    from app.config.money_columns import column_stats

    total = 0
    for columna in MONEY_COLUMNS:
        try:
            total += column_stats(database, columna).out_of_range
        except Exception:  # pragma: no cover - el conteo es informativo
            continue
    return total


def _historical_summary(database) -> tuple[int, int, str]:
    """Cuenta inconsistencias históricas. Sólo lectura; NO repara nada."""
    from app.services.monetary_audit import BUDGET_HEADER_MISMATCH, SEVERITY_CRITICAL
    from app.services.monetary_audit_readonly import MonetaryIntegrityAuditor

    auditor = MonetaryIntegrityAuditor(database)
    audits = auditor.run()
    mismatches = sum(1 for a in audits if a.budget_integrity == BUDGET_HEADER_MISMATCH)
    critical = sum(1 for a in audits if a.severity == SEVERITY_CRITICAL)
    from app.services.monetary_audit import potential_financial_difference

    potencial = potential_financial_difference(audits)
    return mismatches, critical, f"{potencial:,.2f}"


def ensure_money_schema_migrated(
    *,
    runtime_dir: Path,
    build_version: str = "desconocida",
    logger: logging.Logger | None = None,
) -> MoneyMigrationReport:
    """Ejecuta la migración si hace falta. Devuelve el reporte.

    Nunca lanza por un problema de datos: devuelve ``status="aborted"`` para que
    el llamador decida cómo informar al operador. Sólo lanza si el problema es de
    programación o de permisos.
    """
    log = logger or logging.getLogger("femag.money_schema")
    destino_recibo = receipt_path(runtime_dir)

    from app.services.monetary_audit_readonly import resolve_audit_database

    try:
        target = resolve_audit_database()
    except Exception as exc:
        reporte = MoneyMigrationReport(
            status=STATUS_FAILED,
            message=f"No se pudo resolver la conexion de FEMAG: {type(exc).__name__}: {exc}",
        )
        for linea in reporte.summary_lines():
            log.error(linea)
        return reporte

    base_comun = {
        "database": target.database,
        "host": target.host,
        "user": target.user,
    }

    if target.engine != "mysql":
        # SQLite (demo) no tiene el problema de precisión simple: nada que hacer.
        reporte = MoneyMigrationReport(
            status=STATUS_SKIPPED,
            **base_comun,
            message="La configuracion efectiva no es MySQL; no aplica migracion.",
        )
        for linea in reporte.summary_lines():
            log.info(linea)
        return reporte

    database = None
    try:
        database = _open_writable(target)

        from app.config.money_columns import current_column_type, needs_decimal_migration

        pendientes = 0
        for columna in MONEY_COLUMNS:
            actual = current_column_type(database, columna.table, columna.column)
            if actual and needs_decimal_migration(actual, columna):
                pendientes += 1

        if pendientes == 0:
            mismatches, critical, potencial = _historical_summary(database)
            reporte = MoneyMigrationReport(
                status=STATUS_SKIPPED,
                columns_pending_before=0,
                columns_pending_after=0,
                columns_exact_decimal=len(MONEY_COLUMNS),
                historical_mismatches=mismatches,
                historical_critical=critical,
                historical_potential=potencial,
                receipt_path=str(destino_recibo),
                message="Esquema ya migrado; no se ejecuto ningun ALTER.",
                **base_comun,
            )
            for linea in reporte.summary_lines():
                log.info(linea)
            _write_receipt(destino_recibo, reporte, build_version)
            return reporte

        # --- precheck: aborta si algun valor no entra ------------------------
        try:
            stats = precheck_money_columns(database)
        except MoneyMigrationAbort as exc:
            # El precheck lanzó: hay al menos una columna fuera de rango. Se
            # cuenta exactamente para el mensaje, en una segunda pasada de solo
            # lectura, en vez de informar un centinela.
            fuera_real = _count_out_of_range(database)
            reporte = MoneyMigrationReport(
                status=STATUS_ABORTED,
                columns_pending_before=pendientes,
                values_out_of_range=fuera_real,
                message=(
                    f"{exc} No se altero ninguna columna. Hay que revisar antes "
                    "de seguir."
                ),
                **base_comun,
            )
            for linea in reporte.summary_lines():
                log.error(linea)
            _write_receipt(destino_recibo, reporte, build_version)
            return reporte

        fuera = sum(s.out_of_range for s in stats)
        if fuera:
            reporte = MoneyMigrationReport(
                status=STATUS_ABORTED,
                columns_pending_before=pendientes,
                values_out_of_range=fuera,
                message=(
                    f"{fuera} valor(es) no entran en DECIMAL(18,2). No se altero "
                    "ninguna columna."
                ),
                **base_comun,
            )
            for linea in reporte.summary_lines():
                log.error(linea)
            _write_receipt(destino_recibo, reporte, build_version)
            return reporte

        # --- respaldo antes de alterar --------------------------------------
        dump = _make_backup(target, runtime_dir)
        if not dump.ok:
            reporte = MoneyMigrationReport(
                status=STATUS_ABORTED,
                columns_pending_before=pendientes,
                values_out_of_range=fuera,
                values_to_quantize=sum(s.off_scale for s in stats),
                backup_message=dump.message,
                message=(
                    "El respaldo fallo; no se altero ninguna columna. "
                    "No se puede migrar sin respaldo."
                ),
                **base_comun,
            )
            for linea in reporte.summary_lines():
                log.error(linea)
            _write_receipt(destino_recibo, reporte, build_version)
            return reporte

        # --- migración ------------------------------------------------------
        alteradas = migrate_money_columns_to_decimal(database)

        pendientes_final = 0
        exactas = 0
        for columna in MONEY_COLUMNS:
            actual = current_column_type(database, columna.table, columna.column)
            if not actual:
                continue
            if needs_decimal_migration(actual, columna):
                pendientes_final += 1
            else:
                exactas += 1

        mismatches, critical, potencial = _historical_summary(database)
        reporte = MoneyMigrationReport(
            status=STATUS_OK if pendientes_final == 0 else STATUS_ABORTED,
            columns_pending_before=pendientes,
            columns_altered=len(alteradas),
            columns_pending_after=pendientes_final,
            columns_exact_decimal=exactas,
            values_out_of_range=fuera,
            values_to_quantize=sum(s.off_scale for s in stats),
            backup_path=dump.file_path,
            historical_mismatches=mismatches,
            historical_critical=critical,
            historical_potential=potencial,
            receipt_path=str(destino_recibo),
            message=(
                None
                if pendientes_final == 0
                else (
                    f"Migracion PARCIAL: quedaron {pendientes_final} columna(s) "
                    "pendientes. Vuelva a abrir FEMAG para terminar."
                )
            ),
            **base_comun,
        )
        for linea in reporte.summary_lines():
            log.info(linea)
        _write_receipt(destino_recibo, reporte, build_version)
        return reporte
    except Exception as exc:  # pragma: no cover - red de seguridad
        reporte = MoneyMigrationReport(
            status=STATUS_FAILED,
            message=f"{type(exc).__name__}: {exc}",
            **base_comun,
        )
        for linea in reporte.summary_lines():
            log.exception(linea)
        return reporte
    finally:
        if database is not None:
            try:
                database.close()
            except Exception:  # pragma: no cover
                pass

from __future__ import annotations

import ctypes
import logging
import os
import sys
import traceback
from pathlib import Path


def configure_production_runtime() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    runtime_dir = local_app_data / "FEMAG Desktop"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "outputs").mkdir(exist_ok=True)
    (runtime_dir / "backups").mkdir(exist_ok=True)
    (runtime_dir / "logs").mkdir(exist_ok=True)
    os.chdir(runtime_dir)
    os.environ["APP_ENV"] = "production"
    os.environ["FEMAG_DB_ENGINE"] = "mysql"
    os.environ["FEMAG_SECURE_CONFIG"] = "1"
    os.environ["FEMAG_RUNTIME_DIR"] = str(runtime_dir)
    os.environ["BACKUP_DIR"] = str(runtime_dir / "backups")
    return runtime_dir


def _configure_smoke_runtime(runtime_dir: Path) -> None:
    """Use non-secret local settings so the frozen EXE can be smoke-tested in CI."""
    os.environ["FEMAG_SECURE_CONFIG"] = "0"
    os.environ["FEMAG_DEMO"] = "1"
    os.environ["FEMAG_DB_ENGINE"] = "sqlite"
    os.environ["FEMAG_SQLITE_PATH"] = str(runtime_dir / "ci-smoke.sqlite3")
    os.environ["FEMAG_DISABLE_UPDATE_CHECK"] = "1"


def _bootstrap_logging(runtime_dir: Path) -> Path:
    log_path = runtime_dir / "logs" / "startup.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    return log_path


def _show_fatal_error(log_path: Path, exc: BaseException) -> None:
    message = (
        "FEMAG no pudo iniciar.\n\n"
        f"Error: {type(exc).__name__}: {exc}\n\n"
        "Se guardó el detalle técnico en:\n"
        f"{log_path}"
    )
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "FEMAG Desktop - Error de inicio", 0x10)
    except Exception:
        pass


def _run_money_schema_task(runtime_dir: Path, log_path: Path) -> int:
    """Ejecuta la migración monetaria de esquema antes de abrir la aplicación.

    Es un bloqueo de arranque: si la migración no puede completarse, FEMAG no
    abre para operar con una base cuyo esquema de importes no soporta los
    valores correctos.

    La tarea es idempotente y su autoridad es el estado real del esquema, así
    que en un puesto ya migrado no hace absolutely nada. NO repara documentos
    históricos: la migración de esquema y la reparación de presupuestos son
    cosas distintas.
    """
    logger = logging.getLogger("femag.money_schema")
    logger.info("Comprobando esquema de columnas monetarias...")
    try:
        from app.services.money_schema_migration import (
            STATUS_ABORTED,
            STATUS_FAILED,
            ensure_money_schema_migrated,
        )

        report = ensure_money_schema_migrated(
            runtime_dir=runtime_dir,
            build_version=os.getenv("FEMAG_BUILD_VERSION", "produccion"),
            logger=logger,
        )
    except Exception as exc:  # pragma: no cover - red de seguridad
        logger.exception("La tarea de esquema monetario fallo: %s", exc)
        _show_fatal_error(
            log_path,
            RuntimeError(
                "No se pudo comprobar el esquema de importes de FEMAG. "
                f"{type(exc).__name__}: {exc}"
            ),
        )
        return 1

    for line in report.summary_lines():
        logger.info(line)

    if report.status in (STATUS_ABORTED, STATUS_FAILED):
        _show_fatal_error(
            log_path,
            RuntimeError(
                "FEMAG no puede operar con el esquema monetario actual.\n\n"
                + "\n".join(report.summary_lines())
                + "\n\nNo se modificó ningún documento. Corregí la causa y volvé "
                "a abrir FEMAG."
            ),
        )
        return 1
    return 0


def run() -> int:
    runtime_dir = configure_production_runtime()
    args = sys.argv[1:]
    if "--smoke" in args or (
        "--production-health-check" in args and os.getenv("FEMAG_HEALTH_CHECK_CI") == "1"
    ):
        _configure_smoke_runtime(runtime_dir)
    log_path = _bootstrap_logging(runtime_dir)
    logger = logging.getLogger("femag.startup")
    logger.info("Inicio FEMAG Desktop")
    try:
        # Import deliberadamente dentro del bloque protegido: cualquier error de
        # PyInstaller/dependencias debe quedar registrado en startup.log.
        from app.main import main

        # La migración monetaria corre antes de abrir la ventana y antes de
        # delegar en main(), para que nadie pueda operar con importes que la
        # base no puede representar.
        if "--skip-money-schema-task" not in args:
            codigo = _run_money_schema_task(runtime_dir, log_path)
            if codigo != 0:
                return codigo

        args = args or ["--ui"]
        result = main(args)
        logger.info("FEMAG finalizado con código %s", result)
        return result
    except BaseException as exc:
        logger.critical("Fallo fatal durante el inicio de FEMAG", exc_info=True)
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n--- TRACEBACK FATAL ---\n")
                traceback.print_exc(file=handle)
        except Exception:
            pass
        _show_fatal_error(log_path, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthCheckResult:
    ok: bool
    checks: tuple[str, ...]
    error: str = ""


def run_production_health_check() -> HealthCheckResult:
    """Validate a production installation without changing business data."""
    checks: list[str] = []
    database = None
    try:
        from app.config.logging_config import configure_logging
        from app.config.settings import load_settings
        from app.models import ALL_MODELS
        from app.ui.dashboard import DashboardService
        from app.ui.framework import get_ui_framework
        from app.ui.load_orders import build_load_order_form_spec

        settings = load_settings()
        checks.append("config")
        configure_logging()
        checks.append("logging")

        if not ALL_MODELS:
            raise RuntimeError("No se cargaron los modelos de FEMAG.")
        checks.append("models")
        if not DashboardService().view_spec():
            raise RuntimeError("No se pudo construir el dashboard.")
        if not build_load_order_form_spec().detail_columns:
            raise RuntimeError("No se pudo construir Ordenes de Carga.")
        if get_ui_framework().name != "pyqt5libs":
            raise RuntimeError("El framework PyQt esperado no esta disponible.")
        checks.append("ui-components")

        # Inicializa Qt sin mostrar ventanas. En CI se fuerza offscreen desde el workflow.
        from PyQt5.QtWidgets import QApplication

        qt_app = QApplication.instance() or QApplication([])
        if qt_app is None:
            raise RuntimeError("No se pudo inicializar PyQt5.")
        checks.append("pyqt")

        from app.config.database import initialize_runtime_database

        database = initialize_runtime_database(settings)
        database.connect(reuse_if_open=True)
        cursor = database.execute_sql("SELECT 1")
        row = cursor.fetchone()
        if not row or int(row[0]) != 1:
            raise RuntimeError("La consulta de salud de base de datos no devolvio el valor esperado.")
        checks.append("database-readonly")

        # En produccion real validamos el esquema con consultas de metadata. En el smoke
        # SQLite de CI no se exige el esquema MySQL de la planta.
        if settings.db_engine == "mysql" and os.getenv("FEMAG_HEALTH_CHECK_SKIP_SCHEMA") != "1":
            from app.config.schema import validate_runtime_schema

            validate_runtime_schema(database)
            checks.append("schema-readonly")

        return HealthCheckResult(ok=True, checks=tuple(checks))
    except Exception as exc:
        return HealthCheckResult(ok=False, checks=tuple(checks), error=f"{type(exc).__name__}: {exc}")
    finally:
        if database is not None:
            try:
                if not database.is_closed():
                    database.close()
            except Exception:
                pass

"""Resolucion de la base destino para scripts administrativos (#685).

Los scripts que preparan o importan datos no deben terminar en la SQLite de
demo de un checkout por accidente. Este modulo usa la misma resolucion que la
aplicacion y permite abortar con un mensaje claro antes de tocar nada.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import (
    Settings,
    load_settings,
    resolve_effective_connection_settings,
)


@dataclass(frozen=True)
class AdminTarget:
    settings: Settings
    secure_config: bool

    @property
    def is_mysql(self) -> bool:
        return self.settings.db_engine == "mysql"


def resolve_admin_target() -> AdminTarget:
    """Resuelve la conexión como lo haría un puesto, sin depender de estar congelado."""
    secure_config = resolve_effective_connection_settings(packaged_app=False)
    return AdminTarget(settings=load_settings(), secure_config=secure_config)


def describe_admin_target(target: AdminTarget) -> str:
    """Describe el destino sin exponer la contraseña."""
    settings = target.settings
    if settings.db_engine == "mysql":
        return f"mysql {settings.db_host}:{settings.db_port}/{settings.db_name}"
    return f"sqlite {settings.sqlite_path}"


def require_mysql_target(
    target: AdminTarget, *, allow_sqlite: bool = False
) -> str | None:
    """Devuelve un error si el destino no es la MySQL del puesto.

    ``allow_sqlite`` existe solo para que un desarrollador prepare una demo de
    forma explícita; un script de administración no debe hacerlo por accidente.
    """

    if target.is_mysql or allow_sqlite:
        return None
    return (
        "La configuracion resuelve a una base SQLite/demo "
        f"({describe_admin_target(target)}), no a la base MySQL del puesto. "
        "Configure la conexion segura del puesto o use --allow-sqlite si "
        "realmente quiere preparar la demo."
    )


__all__ = [
    "AdminTarget",
    "describe_admin_target",
    "require_mysql_target",
    "resolve_admin_target",
]

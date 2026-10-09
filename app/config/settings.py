import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared for runtime.
    load_dotenv = None


@dataclass(frozen=True)
class Settings:
    app_env: str
    db_engine: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    sqlite_path: Path
    demo: bool
    backup_dir: Path
    backup_extra_dir: Path | None
    log_level: str
    whatsapp_enabled: bool = False
    whatsapp_api_url: str = ""
    whatsapp_api_key: str = ""
    whatsapp_instance_id: str = "default"
    whatsapp_api_timeout: float = 15.0


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _flag_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def resolve_effective_connection_settings(
    *,
    demo_mode: bool = False,
    configure: bool = False,
    packaged_app: bool | None = None,
) -> bool:
    """Decide si la ejecución usa la configuración segura del puesto y la exige.

    Es el preámbulo de conexión de FEMAG. Todo lo que abre la base en este
    proyecto pasa por acá: si existe configuración segura guardada (DPAPI en
    ``%LOCALAPPDATA%\\FEMAG Desktop``), se fuerza MySQL **pese a lo que diga
    el ``.env``**, para que un ``.env`` de demo heredado no redirija la
    aplicación a SQLite por accidente.

    Ajusta sólo variables del proceso actual (no toca disco ni base) y devuelve
    ``True`` cuando la conexión debe venir de la configuración segura.

    Vive acá, y no inline en ``app.main.run_ui()``, porque el auditor monetario
    la usa para conectarse **a la misma base que la aplicación**. Si hubiera dos
    copias de esta lógica, el auditor podría auditar una base y la aplicación
    estar sobre otra, y delivers un informe falso sobre datos que nadie mira.

    ``packaged_app`` detecta la app congelada de producción; se puede pasar
    explícitamente para no depender de esa detección.
    """
    from app.config.secure_credentials import has_runtime_configuration

    if packaged_app is None:
        packaged_app = bool(getattr(sys, "frozen", False))
    saved_runtime_config = has_runtime_configuration()
    use_secure_config = bool(
        not demo_mode
        and (
            configure
            or packaged_app
            or saved_runtime_config
            or os.getenv("FEMAG_SECURE_CONFIG") == "1"
        )
    )
    if use_secure_config:
        # Toda ejecución normal (EXE o source) usa la configuración segura
        # del puesto cuando existe. Así evitamos que .env o variables viejas
        # de demo redirijan FEMAG a SQLite por accidente.
        os.environ["FEMAG_SECURE_CONFIG"] = "1"
        os.environ["FEMAG_DEMO"] = "0"
        os.environ["FEMAG_DB_ENGINE"] = "mysql"
    return use_secure_config


def load_settings() -> Settings:
    secure_connection = None
    if _flag_enabled(os.getenv("FEMAG_SECURE_CONFIG")):
        from app.config.secure_credentials import load_runtime_connection

        secure_connection = load_runtime_connection()

    env_file = os.getenv("FEMAG_ENV_FILE", ".env")
    # El .env completa valores faltantes, pero nunca debe pisar variables
    # explícitas del proceso/shell. Esto evita que una configuración de demo
    # contamine una ejecución MySQL iniciada expresamente por el operador.
    if load_dotenv:
        load_dotenv(env_file, override=False)

    demo = False if secure_connection else _flag_enabled(os.getenv("FEMAG_DEMO"))
    db_engine = (
        "mysql"
        if secure_connection
        else os.getenv("FEMAG_DB_ENGINE", "sqlite" if demo else "mysql").strip().lower()
    )
    if db_engine not in {"mysql", "sqlite"}:
        raise ValueError("FEMAG_DB_ENGINE debe ser 'mysql' o 'sqlite'.")

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        db_engine=db_engine,
        db_host=secure_connection.host if secure_connection else os.getenv("DB_HOST", "127.0.0.1"),
        db_port=secure_connection.port if secure_connection else int(os.getenv("DB_PORT", "3306")),
        db_name=secure_connection.database if secure_connection else os.getenv("DB_NAME", "femag"),
        db_user=secure_connection.user if secure_connection else os.getenv("DB_USER", "femag"),
        db_password=secure_connection.password if secure_connection else os.getenv("DB_PASSWORD", ""),
        sqlite_path=Path(os.getenv("FEMAG_SQLITE_PATH", "femag_demo.sqlite3")),
        demo=demo,
        backup_dir=Path(os.getenv("BACKUP_DIR", "backups")),
        backup_extra_dir=_optional_path(os.getenv("BACKUP_EXTRA_DIR")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        whatsapp_enabled=_flag_enabled(os.getenv("WHATSAPP_ENABLED", "false")),
        whatsapp_api_url=os.getenv("WHATSAPP_API_URL", "").strip().rstrip("/"),
        whatsapp_api_key=os.getenv("WHATSAPP_API_KEY", "").strip(),
        whatsapp_instance_id=os.getenv("WHATSAPP_INSTANCE_ID", "default").strip(),
        whatsapp_api_timeout=float(os.getenv("WHATSAPP_API_TIMEOUT", "15")),
    )

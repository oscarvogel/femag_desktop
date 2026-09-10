import os
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
    whatsapp_enabled: bool
    whatsapp_api_url: str
    whatsapp_api_key: str
    whatsapp_instance_id: str
    whatsapp_api_timeout: float


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _flag_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def load_settings() -> Settings:
    secure_connection = None
    if _flag_enabled(os.getenv("FEMAG_SECURE_CONFIG")):
        from app.config.secure_credentials import load_runtime_connection

        secure_connection = load_runtime_connection()

    env_file = os.getenv("FEMAG_ENV_FILE", ".env")
    # El .env local es la fuente unica para configuracion no sensible al modo de DB,
    # incluido WhatsApp. Las credenciales DB seguras siguen teniendo prioridad.
    if load_dotenv:
        load_dotenv(env_file, override=True)

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

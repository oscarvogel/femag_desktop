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
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    backup_dir: Path
    backup_extra_dir: Path | None
    log_level: str


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def load_settings() -> Settings:
    env_file = os.getenv("FEMAG_ENV_FILE", ".env")
    if load_dotenv:
        load_dotenv(env_file, override=True)

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_name=os.getenv("DB_NAME", "femag"),
        db_user=os.getenv("DB_USER", "femag"),
        db_password=os.getenv("DB_PASSWORD", ""),
        backup_dir=Path(os.getenv("BACKUP_DIR", "backups")),
        backup_extra_dir=_optional_path(os.getenv("BACKUP_EXTRA_DIR")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )

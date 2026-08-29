import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import Settings, load_settings


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if os.getenv("APP_ENV") == "production":
        runtime_dir = Path(
            os.environ.get(
                "FEMAG_RUNTIME_DIR",
                Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                / "FEMAG Desktop",
            )
        )
        log_dir = runtime_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / "femag.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )

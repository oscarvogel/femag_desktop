import logging

from app.config.settings import Settings, load_settings


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

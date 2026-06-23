import argparse

from app.config.logging_config import configure_logging
from app.config.settings import load_settings
from app.ui.desktop_app import run_desktop_app


def smoke_check() -> str:
    load_settings()
    configure_logging()
    from app.models import ALL_MODELS
    from app.ui.dashboard import future_module_message
    from app.ui.framework import get_ui_framework

    assert ALL_MODELS
    assert future_module_message()
    assert get_ui_framework().name == "pyqt5libs"
    return "FEMAG smoke OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="femag-desktop")
    parser.add_argument("--smoke", action="store_true", help="Validate imports/config without opening UI")
    args = parser.parse_args(argv)
    if args.smoke:
        print(smoke_check())
        return 0

    load_settings()
    configure_logging()
    return run_desktop_app()


if __name__ == "__main__":
    raise SystemExit(main())

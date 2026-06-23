import argparse

from app.config.logging_config import configure_logging
from app.config.settings import load_settings
from app.ui.desktop_app import run_desktop_app


def smoke_check() -> str:
    load_settings()
    configure_logging()
    from app.models import ALL_MODELS
    from app.ui.dashboard import DashboardService, future_module_message
    from app.ui.framework import get_ui_framework
    from app.ui.load_orders import build_load_order_form_spec

    assert ALL_MODELS
    assert future_module_message()
    assert DashboardService().view_spec()
    assert build_load_order_form_spec().detail_columns
    assert get_ui_framework().name == "pyqt5libs"
    return "FEMAG smoke OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="femag-desktop")
    parser.add_argument("--smoke", action="store_true", help="Validate imports/config without opening UI")
    parser.add_argument("--demo", action="store_true", help="Use demo runtime data when opening the UI")
    args = parser.parse_args(argv)
    if args.smoke:
        print(smoke_check())
        return 0

    load_settings()
    configure_logging()
    return run_desktop_app(demo_mode=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())

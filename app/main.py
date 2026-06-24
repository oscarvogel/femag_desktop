import argparse
import sys

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


def run_ui(*, demo_mode: bool = False) -> int:
    load_settings()
    configure_logging()
    try:
        return run_desktop_app(demo_mode=demo_mode)
    except ImportError as exc:  # pragma: no cover - depends on workstation setup.
        raise RuntimeError(
            "PyQt5 no esta instalado. Instalar dependencias con `pip install -r requirements.txt`."
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="femag-desktop")
    parser.add_argument("--smoke", action="store_true", help="Validate imports/config without opening UI")
    parser.add_argument("--ui", action="store_true", help="Open FEMAG Desktop UI for workstation validation")
    parser.add_argument("--demo-ui", action="store_true", help="Open FEMAG Desktop UI with local demo data")
    args = parser.parse_args(argv)
    if args.smoke:
        print(smoke_check())
        return 0
    if args.ui or args.demo_ui:
        try:
            return run_ui(demo_mode=args.demo_ui)
        except RuntimeError as exc:
            print(f"No se pudo abrir FEMAG Desktop UI: {exc}", file=sys.stderr)
            return 1

    print("FEMAG Desktop UI requires a workstation session. Use --ui or --demo-ui to open the desktop window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import argparse

from app.config.logging_config import configure_logging
from app.config.settings import load_settings


def smoke_check() -> str:
    load_settings()
    configure_logging()
    from app.models import ALL_MODELS
    from app.ui.dashboard import future_module_message

    assert ALL_MODELS
    assert future_module_message()
    return "FEMAG smoke OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="femag-desktop")
    parser.add_argument("--smoke", action="store_true", help="Validate imports/config without opening UI")
    args = parser.parse_args(argv)
    if args.smoke:
        print(smoke_check())
        return 0

    print("FEMAG Desktop UI requires a workstation session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os

from app.production_entrypoint import configure_production_runtime


def run() -> int:
    # Usa exactamente el mismo runtime y credenciales seguras que FEMAG Desktop.
    runtime_dir = configure_production_runtime()
    os.environ.setdefault(
        "FEMAG_ENV_FILE",
        str(runtime_dir / "managerial_summary.env"),
    )

    from app.jobs.send_managerial_summary import main

    return main()


if __name__ == "__main__":
    raise SystemExit(run())

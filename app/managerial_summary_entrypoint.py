from __future__ import annotations

import os

from dotenv import load_dotenv

from app.production_entrypoint import configure_production_runtime


def run() -> int:
    # Usa exactamente el mismo runtime y credenciales seguras que FEMAG Desktop.
    runtime_dir = configure_production_runtime()
    env_path = runtime_dir / "managerial_summary.env"
    os.environ["FEMAG_ENV_FILE"] = str(env_path)

    # Para este job, la configuracion dedicada debe prevalecer sobre variables
    # viejas definidas en Windows o heredadas por el proceso. Esto afecta solo
    # lo que exista en managerial_summary.env; MySQL sigue usando secure config.
    if env_path.is_file():
        load_dotenv(env_path, override=True)

    from app.jobs.send_managerial_summary import main

    return main()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from app.production_entrypoint import configure_production_runtime


def _run_rates_command(command: str, args: list[str]) -> int:
    """Ejecuta la actualizacion o la importacion historica de cotizaciones.

    El EXE gerencial ya tiene el runtime, la configuracion segura y las
    dependencias de base de datos; se reutiliza para no exigir Python en el
    servidor de la fabrica.
    """
    if command == "--update-rates":
        from app.jobs.update_exchange_rates import main

        return main(args)
    if command == "--import-rates":
        from app.jobs.import_historical_exchange_rates import main

        return main(args)
    raise ValueError(f"Comando de cotizaciones desconocido: {command}")


def run() -> int:
    args = list(sys.argv[1:])
    command = args[0] if args else ""

    # Las cotizaciones tienen su propio runtime/configuracion: pueden usar la
    # configuracion segura de FEMAG o un exchange_rates.env para tareas/SYSTEM.
    # No se fuerza el runtime gerencial ni FEMAG_SECURE_CONFIG.
    if command in {"--update-rates", "--import-rates"}:
        return _run_rates_command(command, args[1:])

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

    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())

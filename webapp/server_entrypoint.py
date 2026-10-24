"""Punto de entrada del servidor webapp empaquetado (PyInstaller).

El ejecutable congelado tiene que arrancar solo en un Windows Server 2019 que
no tiene Python, y dejar registro de lo que pasa: el servicio se levanta desde
una tarea programada, sin consola y sin log, y cuando algo falla no hay nada
para mirar. Este módulo deja las dos cosas resueltas: log a archivo y salida
con codigo de error.

Modos:

- sin argumentos: levanta el servidor con la configuracion de
  ``C:\\ProgramData\\FEMAG\\webapp.env``.
- ``--smoke``: arranca con una base SQLite temporal, sin tocar la base real,
  responde ``/health`` y sale con codigo 0. Es lo que valida el binario
  congelado en CI.
- ``--health-check``: consulta el ``/health`` del servidor ya levantado y
  devuelve 0 si responde bien.

A diferencia de la app de escritorio, aqui NO se muestra una ventana de error:
el servidor corre como servicio, en la sesion 0, y un MessageBox en esa sesion
queda esperando a un usuario que no existe. El error va al log.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_CONFIG_DIR = Path(r"C:\ProgramData\FEMAG")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HEALTH_TIMEOUT_SECONDS = 45


def config_directory() -> Path:
    """Carpeta de configuracion del servidor.

    El instalador y el script de despliegue la fijan en
    ``FEMAG_CONFIG_DIR``; si no, es la de la fabrica.
    """
    return Path(os.environ.get("FEMAG_CONFIG_DIR") or DEFAULT_CONFIG_DIR)


def runtime_directory() -> Path:
    """Prepara la carpeta de runtime y sus subcarpetas."""
    base = config_directory()
    (base / "logs").mkdir(parents=True, exist_ok=True)
    return base


def configure_production_runtime() -> Path:
    """Define el runtime del servidor: configuracion, logs y motor de base."""
    runtime_dir = runtime_directory()
    os.environ.setdefault("APP_ENV", "production")
    os.environ.setdefault("FEMAG_DB_ENGINE", "mysql")
    # El servicio NO crea ni altera tablas. La migracion de esquema la aplica
    # un administrador desde FEMAG Desktop, antes de levantar el servidor.
    os.environ.setdefault("FEMAG_AUTO_MIGRATE_SCHEMA", "0")
    # El servidor lee la conexion del archivo de configuracion (DB_USER,
    # DB_PASSWORD), no de las credenciales cifradas con DPAPI: corre como
    # SYSTEM y el archivo se protege con permisos, no con cifrado por usuario.
    os.environ.setdefault("FEMAG_SECURE_CONFIG", "0")
    os.environ.setdefault("FEMAG_RUNTIME_DIR", str(runtime_dir))
    os.environ.setdefault("FEMAG_ENV_FILE", str(runtime_dir / "webapp.env"))
    os.environ.setdefault("FEMAG_WEB_SECRET_FILE", str(runtime_dir / "webapp_secret.key"))
    os.chdir(runtime_dir)
    return runtime_dir


def bootstrap_logging(runtime_dir: Path) -> Path:
    """Deja el log del servidor en un archivo, no en una consola que no existe."""
    log_path = runtime_dir / "logs" / "webapp_server.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    return log_path


def _log_exception(logger: logging.Logger, log_path: Path, message: str) -> None:
    logger.critical(message, exc_info=True)
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n--- TRACEBACK FATAL ---\n")
            traceback.print_exc(file=handle)
    except OSError:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _health_url(host: str, port: int) -> str:
    # 0.0.0.0 no es una direccion de destino: para consultarlo hay que usar el
    # loopback.
    destino = "127.0.0.1" if host in ("0.0.0.0", "") else host
    return f"http://{destino}:{port}/health"


def _probe_health(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _probe_page(url: str, timeout: float = 10.0) -> bool:
    """Comprueba que una pagina se renderiza.

    En un congelado las plantillas de Flask viajan como datos: si el spec no
    las recoge, ``/health`` sigue respondiendo bien (no renderiza nada) y el
    fallo aparece recien cuando el operario abre la pantalla.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _build_qr_sheet() -> bool:
    """Genera la hoja de QR de turnos.

    Es lo que usa ``reportlab.graphics.barcode.qr``: en un congelado,
    reportlab necesita sus ``datas`` (las fuentes) y sus ``hiddenimports`` (el
    modulo de barcode). Sin eso, el QR no se genera.
    """
    try:
        from webapp.production_service import SHIFTS
        from webapp.qr_sheet import build_turno_sheet

        pdf = build_turno_sheet(SHIFTS, lambda turno: f"http://127.0.0.1/produccion?turno={turno}")
        return bool(pdf)
    except Exception:
        return False


def _wait_for_health(url: str, timeout: int = HEALTH_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _probe_health(url):
            return True
        time.sleep(1.0)
    return False


def serve_forever() -> int:
    """Levanta el servidor y no vuelve nunca (es un servicio)."""
    runtime_dir = configure_production_runtime()
    log_path = bootstrap_logging(runtime_dir)
    logger = logging.getLogger("femag.webapp_server")

    host = os.getenv("FEMAG_WEB_HOST", DEFAULT_HOST)
    port = int(os.getenv("FEMAG_WEB_PORT", str(DEFAULT_PORT)))
    logger.info("Arrancando el servidor webapp de FEMAG en %s:%s", host, port)

    try:
        from waitress import serve

        from app.config.database import initialize_runtime_database
        from webapp import create_app

        initialize_runtime_database()
        serve(create_app(), host=host, port=port)
        return 0
    except BaseException:
        _log_exception(logger, log_path, "Fallo fatal al arrancar el servidor webapp")
        return 1


def run_smoke() -> int:
    """Arranca con una base temporal, responde /health y sale con codigo 0.

    No toca la base real: es la validacion del binario congelado en CI y en
    la maquina de desarrollo.
    """
    runtime_dir = runtime_directory()
    log_path = bootstrap_logging(runtime_dir)
    logger = logging.getLogger("femag.webapp_server")

    smoke_dir = runtime_dir / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FEMAG_SECURE_CONFIG"] = "0"
    os.environ["FEMAG_DEMO"] = "1"
    os.environ["FEMAG_DB_ENGINE"] = "sqlite"
    os.environ["FEMAG_AUTO_MIGRATE_SCHEMA"] = "0"
    os.environ["FEMAG_SQLITE_PATH"] = str(smoke_dir / "smoke.sqlite3")
    os.environ["FEMAG_WEB_SECRET_FILE"] = str(smoke_dir / "smoke_secret.key")

    try:
        from waitress import create_server

        from app.config.database import initialize_runtime_database
        from app.config.schema import ensure_runtime_schema
        from webapp import create_app

        database = initialize_runtime_database()
        ensure_runtime_schema(database)

        port = _free_port()
        server = create_server(create_app(), host="127.0.0.1", port=port)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base = _health_url("127.0.0.1", port).rsplit("/health", 1)[0]
        try:
            sano = _wait_for_health(base + "/health")
            renderiza = sano and _probe_page(base + "/login")
            qr_ok = _build_qr_sheet()
        finally:
            server.close()
    except BaseException:
        _log_exception(logger, log_path, "Fallo fatal en el smoke test del servidor webapp")
        return 1

    if not sano:
        logger.error("El smoke test no pudo responder /health")
        return 1
    if not renderiza:
        logger.error("El smoke test no pudo renderizar /login (faltan las plantillas)")
        return 1
    if not qr_ok:
        logger.error("El smoke test no pudo generar la hoja de QR (falta reportlab)")
        return 1
    logger.info("Smoke test del servidor webapp OK")
    return 0


def run_health_check() -> int:
    """Consulta el /health del servidor ya levantado. 0 si responde bien."""
    runtime_dir = runtime_directory()
    bootstrap_logging(runtime_dir)
    logger = logging.getLogger("femag.webapp_server")

    host = os.getenv("FEMAG_WEB_HOST", DEFAULT_HOST)
    port = int(os.getenv("FEMAG_WEB_PORT", str(DEFAULT_PORT)))
    url = _health_url(host, port)
    sano = _probe_health(url)
    if sano:
        logger.info("Health check OK: %s", url)
    else:
        logger.error("Health check fallido: %s", url)
    return 0 if sano else 1


def run() -> int:
    args = sys.argv[1:]
    if "--smoke" in args:
        return run_smoke()
    if "--health-check" in args:
        return run_health_check()
    return serve_forever()


if __name__ == "__main__":
    raise SystemExit(run())

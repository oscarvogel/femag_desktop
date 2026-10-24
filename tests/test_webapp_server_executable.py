"""Pruebas del ejecutable empaquetado del servidor webapp (#776).

El ejecutable congelado es lo que corre en el Windows Server 2019 de la
fabrica. Lo que se rompe en un congelado y no en el codigo normal son dos
cosas: las plantillas de Flask (viajan como datos) y reportlab (necesita sus
datas y sus hiddenimports). Por eso el smoke del ejecutable comprueba las
tres: /health, el render de una pagina y la hoja de QR.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "webapp" / "server_entrypoint.py"
SPEC = ROOT / "installer" / "FEMAG_Webapp_Server.spec"
FROZEN_DIR = ROOT / "dist" / "FEMAG Webapp Server"


def _run_entrypoint(args, config_dir, extra_env=None):
    env = dict(os.environ)
    env["FEMAG_CONFIG_DIR"] = str(config_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("FEMAG_ENV_FILE", None)
    env.pop("FEMAG_WEB_SECRET_FILE", None)
    env.pop("FEMAG_DB_ENGINE", None)
    env.pop("FEMAG_DEMO", None)
    env.pop("FEMAG_SECURE_CONFIG", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "webapp.server_entrypoint", *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        timeout=240,
    )


def test_server_entrypoint_exists_and_declares_its_modes():
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert "--smoke" in content
    assert "--health-check" in content
    # El servicio no crea ni altera tablas: la migracion la aplica un
    # administrador desde FEMAG Desktop.
    assert 'FEMAG_AUTO_MIGRATE_SCHEMA", "0"' in content
    # El log va a un archivo: el servicio corre sin consola.
    assert "webapp_server.log" in content


def test_server_entrypoint_smoke_mode_passes_and_leaves_a_log(tmp_path):
    completed = _run_entrypoint(["--smoke"], tmp_path)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")

    log = tmp_path / "logs" / "webapp_server.log"
    assert log.exists(), "El smoke tiene que dejar log."
    assert "Smoke test" in log.read_text(encoding="utf-8")


def test_server_entrypoint_health_check_fails_when_nothing_is_listening(tmp_path):
    # Un puerto alto que casi seguro esta libre.
    completed = _run_entrypoint(
        ["--health-check"], tmp_path, {"FEMAG_WEB_HOST": "127.0.0.1", "FEMAG_WEB_PORT": "45999"}
    )

    assert completed.returncode == 1


def test_webapp_server_spec_ships_templates_and_excludes_pyqt():
    content = SPEC.read_text(encoding="utf-8")

    # Sin esto, el congelado arranca pero /login da error: las plantillas de
    # Jinja quedan dentro del PYZ y Jinja no las encuentra en disco.
    assert 'collect_data_files("webapp", includes=["templates/*.html"])' in content
    # El codigo QR de reportlab necesita el modulo de barcode y las fuentes.
    assert "reportlab.graphics.barcode" in content
    assert 'collect_data_files("reportlab")' in content
    # La webapp no usa PyQt: dejarlo fuera mantiene el paquete chico.
    assert "PyQt5" in content
    # Con consola para que el log del servicio pueda capturar stdout/stderr.
    assert "console=True" in content


def test_frozen_server_package_has_no_pyqt_and_no_secrets():
    if not FROZEN_DIR.exists():
        pytest.skip("El ejecutable congelado no esta construido en este checkout.")

    offenders = [
        path.name
        for path in FROZEN_DIR.rglob("*")
        if path.is_file() and "pyqt" in path.name.lower()
    ]
    assert not offenders, offenders

    # El CI del escritorio prohibe esto en el artefacto; el servidor tampoco
    # puede llevar un .env ni una clave.
    for pattern in ("*.env", "*.key", "*.credential", "*.pem"):
        matches = [
            path.name
            for path in FROZEN_DIR.rglob(pattern)
            if path.is_file()
        ]
        assert not matches, (pattern, matches)

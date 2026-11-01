"""Tests del script de dump diario que se despliega en el servidor.

``backup_mysql_all_databases.ps1`` se copia al servidor (por ejemplo
``C:\\resguardo``) **solo**: no hay repositorio ni paquete ``app`` ahi. Estos
tests lo ejercitan con clientes MySQL falsos, para no depender de un MySQL
instalado ni de una base real.

La regresion que motivó el issue #15: en el servidor fallaba con
"No se encontro el script de dump" porque el script exigia el
``backup_mysql_databases.py`` hermano aunque MySQL Client ya estaba instalado.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup_mysql_all_databases.ps1"
PYTHON_DUMP = ROOT / "scripts" / "backup_mysql_databases.py"

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")

PASSWORD = "clave-de-prueba-123"

pytestmark = pytest.mark.skipif(
    POWERSHELL is None,
    reason="Se necesita PowerShell para ejecutar el script del servidor.",
)


def _write_fake_tool(path: Path, stdout=(), stderr=(), exit_code: int = 0) -> Path:
    """Escribe un cliente MySQL falso (.cmd) con la salida controlada.

    El texto no lleva parentesis, comillas ni redirecciones porque ``echo`` en
    cmd.exe los interpreta: el fake tiene que fallar exactamente como falla el
    cliente real, no por un problema de quoting.
    """
    lines = ["@echo off"]
    for line in stdout:
        lines.append(f"echo {line}")
    for line in stderr:
        lines.append(f">&2 echo {line}")
    lines.append(f"exit /b {exit_code}")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return path


def _run_script(
    arguments=(),
    backup_dir: Path = None,
    script: Path = None,
    host: str = "127.0.0.1",
    port: str = "3306",
    user: str = "usuario_prueba",
    password: str = PASSWORD,
    timeout: int = 180,
) -> subprocess.CompletedProcess:
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script or SCRIPT),
        "-MysqlHost",
        host,
        "-MysqlPort",
        port,
        "-MysqlUser",
        user,
        "-MysqlPassword",
        password,
    ]
    if backup_dir is not None:
        command += ["-BackupDir", str(backup_dir)]
    command += list(arguments)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _read_log(backup_dir: Path) -> str:
    return (backup_dir / "backup.log").read_text(encoding="utf-8-sig")


def _read_manifest(backup_dir: Path) -> dict:
    return json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8-sig"))


def test_daily_dump_script_is_utf8_with_bom_for_powershell_5_1():
    """Windows Server 2019 corre PowerShell 5.1.

    Un .ps1 sin BOM se lee como Windows-1252 y los acentos se rompen.
    """
    raw = SCRIPT.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf"), (
        "backup_mysql_all_databases.ps1 necesita BOM UTF-8 para que PowerShell 5.1 lo lea bien."
    )


def test_daily_dump_script_does_not_need_the_repository():
    """El script se despliega solo: no puede depender del checkout ni de ``app``."""
    content = SCRIPT.read_text(encoding="utf-8-sig")

    assert "app.config" not in content
    assert "sys.path" not in content
    assert "CAMBIAR_CLAVE" in content


def test_daily_dump_works_with_only_the_ps1_on_the_server(tmp_path):
    """Regresion del issue #15.

    En el servidor hay ``C:\\resguardo\\backup_mysql_all_databases.ps1`` y nada
    mas: el ``backup_mysql_databases.py`` hermano no viaja. Con MySQL Client
    instalado el dump tiene que salir igual.
    """
    resguardo = tmp_path / "resguardo"
    resguardo.mkdir()
    script = resguardo / SCRIPT.name
    shutil.copy2(SCRIPT, script)

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(fakebin / "mysqldump.cmd", stdout=["-- dump de prueba"])
    _write_fake_tool(
        fakebin / "mysql.cmd",
        stdout=["femag_desktop", "information_schema", "mysql"],
    )
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-MysqldumpPath",
            str(fakebin / "mysqldump.cmd"),
            "-MysqlClientPath",
            str(fakebin / "mysql.cmd"),
        ],
        backup_dir,
        script=script,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No se encontro el script de dump" not in result.stdout
    assert "No se encontro el script de dump" not in _read_log(backup_dir)
    assert "Motor de dump: mysqldump" in result.stdout
    assert (backup_dir / "femag_desktop.sql").read_text(encoding="utf-8").strip() == "-- dump de prueba"


def test_daily_dump_writes_one_file_per_database_plus_manifest_and_log(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(fakebin / "mysqldump.cmd", stdout=["-- dump de prueba", "ARGV %*"])
    _write_fake_tool(
        fakebin / "mysql.cmd",
        stdout=["femag_desktop", "femag_demo", "information_schema", "mysql", "performance_schema", "sys"],
    )
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-MysqldumpPath",
            str(fakebin / "mysqldump.cmd"),
            "-MysqlClientPath",
            str(fakebin / "mysql.cmd"),
        ],
        backup_dir,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (backup_dir / "femag_desktop.sql").exists()
    assert (backup_dir / "femag_demo.sql").exists()

    # Las bases del sistema no se respaldan.
    assert not (backup_dir / "information_schema.sql").exists()
    assert not (backup_dir / "mysql.sql").exists()
    assert not (backup_dir / "sys.sql").exists()

    manifest = _read_manifest(backup_dir)
    assert [entry["database"] for entry in manifest["databases"]] == ["femag_demo", "femag_desktop"]
    assert all(entry["status"] == "success" for entry in manifest["databases"])
    assert manifest["created_at"]

    log = _read_log(backup_dir)
    assert "Inicio dump MySQL" in log
    assert "OK femag_desktop" in log
    assert "Fin (exit=0)" in log


def test_daily_dump_skips_the_databases_excluded_by_configuration(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(fakebin / "mysqldump.cmd", stdout=["-- dump de prueba"])
    _write_fake_tool(fakebin / "mysql.cmd", stdout=["femag_desktop", "pruebas", "femag_demo"])
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-MysqldumpPath",
            str(fakebin / "mysqldump.cmd"),
            "-MysqlClientPath",
            str(fakebin / "mysql.cmd"),
            "-ExcludeDatabases",
            "pruebas",
        ],
        backup_dir,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (backup_dir / "femag_desktop.sql").exists()
    assert (backup_dir / "femag_demo.sql").exists()
    assert not (backup_dir / "pruebas.sql").exists()

    manifest = _read_manifest(backup_dir)
    assert [entry["database"] for entry in manifest["databases"]] == ["femag_demo", "femag_desktop"]


def test_daily_dump_keeps_the_whole_error_of_a_failed_dump(tmp_path):
    """El log tiene que decir TODO lo que dijo la herramienta.

    Con ``2>&1`` y ``$ErrorActionPreference = "Stop"`` la primera linea de
    stderr se convertia en excepcion terminante y el resto se perdia: el log
    quedaba con una sola linea y sin poder saber que paso.
    """
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(
        fakebin / "mysqldump.cmd",
        stderr=[
            "ERROR 1045 28000 Access denied for user",
            "Traceback most recent call last",
            "  File dump.py line 3 in main",
        ],
        exit_code=1,
    )
    _write_fake_tool(fakebin / "mysql.cmd", stdout=["femag_desktop"])
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-MysqldumpPath",
            str(fakebin / "mysqldump.cmd"),
            "-MysqlClientPath",
            str(fakebin / "mysql.cmd"),
        ],
        backup_dir,
    )

    assert result.returncode == 1, result.stdout + result.stderr

    log = _read_log(backup_dir)
    assert "ERROR 1045 28000 Access denied for user" in log
    assert "Traceback most recent call last" in log
    assert "File dump.py line 3 in main" in log
    assert "Fin (exit=1)" in log

    # Un dump fallido no deja un .sql a medias que alguien pueda restaurar.
    assert not (backup_dir / "femag_desktop.sql").exists()
    assert not list(backup_dir.glob("*.tmp"))

    manifest = _read_manifest(backup_dir)
    assert manifest["databases"][0]["status"] == "error"
    assert "Traceback most recent call last" in manifest["databases"][0]["message"]


def test_daily_dump_never_puts_the_password_in_the_command_line(tmp_path):
    """La clave viaja por MYSQL_PWD, nunca como argumento.

    Un argumento queda en la linea de comandos del proceso y se ve en el
    administrador de tareas y en los registros.
    """
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(
        fakebin / "mysqldump.cmd",
        stdout=["ARGV %*", "ENV_MYSQL_PWD=%MYSQL_PWD%"],
    )
    _write_fake_tool(fakebin / "mysql.cmd", stdout=["femag_desktop"])
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-MysqldumpPath",
            str(fakebin / "mysqldump.cmd"),
            "-MysqlClientPath",
            str(fakebin / "mysql.cmd"),
        ],
        backup_dir,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    dump = (backup_dir / "femag_desktop.sql").read_text(encoding="utf-8")

    assert PASSWORD not in [line for line in dump.splitlines() if line.startswith("ARGV")][0]
    assert f"ENV_MYSQL_PWD={PASSWORD}" in dump


def test_daily_dump_passes_the_right_arguments_to_the_python_exporter(tmp_path):
    """El motor Python es el respaldo cuando MySQL Client no esta instalado."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    _write_fake_tool(
        fakebin / "python.cmd",
        stdout=["PYTHON_ARGS %*", "ENV_MYSQL_USER=%MYSQL_USER%"],
    )
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-DumpEngine",
            "python",
            "-PythonPath",
            str(fakebin / "python.cmd"),
        ],
        backup_dir,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Motor de dump: python" in result.stdout

    log = _read_log(backup_dir)
    assert "--host 127.0.0.1" in log
    assert "--port 3306" in log
    assert f"--backup-dir {backup_dir}" in log
    assert "--dump-engine python" in log
    assert "--overwrite" in log
    assert "ENV_MYSQL_USER=usuario_prueba" in log


def test_daily_dump_falls_back_to_python_when_mysqldump_is_not_installed(tmp_path):
    """Sin MySQL Client el script usa el exportador Python y no se cae.

    Aca se corre el exportador real contra un puerto cerrado: el error que
    tiene que quedar en el log es el de conexion, no un ``ModuleNotFoundError``
    por el paquete ``app``, que no existe en el servidor.
    """
    pytest.importorskip("pymysql")
    backup_dir = tmp_path / "backups"

    result = _run_script(
        [
            "-DumpEngine",
            "python",
            "-PythonPath",
            sys.executable,
        ],
        backup_dir,
        port="1",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "Motor de dump: python" in result.stdout

    log = _read_log(backup_dir)
    assert "Can't connect to MySQL server" in log
    assert "No module named" not in log


def test_dump_exporter_runs_without_the_app_package(tmp_path):
    """El exportador tiene que sobrevivir fuera del checkout.

    En el servidor no existe el paquete ``app``: si el import fuera
    obligatorio, el respaldo caeria con ModuleNotFoundError.
    """
    pytest.importorskip("pymysql")

    standalone = tmp_path / "resguardo"
    standalone.mkdir()
    shutil.copy2(PYTHON_DUMP, standalone / PYTHON_DUMP.name)

    # Se corre como script, que es como lo invoca el .ps1 en el servidor.
    completed = subprocess.run(
        [
            sys.executable,
            str(standalone / PYTHON_DUMP.name),
            "--host",
            "127.0.0.1",
            "--port",
            "1",
            "--user",
            "usuario_prueba",
            "--password",
            PASSWORD,
            "--backup-dir",
            str(tmp_path / "backups"),
            "--dump-engine",
            "python",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(standalone),
        timeout=120,
    )

    # El puerto 1 no tiene nada escuchando: el error que tiene que quedar es
    # el de conexion, no un ModuleNotFoundError por el paquete app.
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "Can't connect to MySQL server" in completed.stderr
    assert "No module named" not in completed.stderr


def test_dump_exporter_exposes_the_connection_class_without_the_app_package(tmp_path):
    """Importado como modulo, el exportador define su propia clase de conexion."""
    pytest.importorskip("pymysql")

    standalone = tmp_path / "resguardo"
    standalone.mkdir()
    shutil.copy2(PYTHON_DUMP, standalone / PYTHON_DUMP.name)

    codigo = (
        "import importlib.util, sys\n"
        "ruta = r'%s'\n"
        "spec = importlib.util.spec_from_file_location('dump', ruta)\n"
        "modulo = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = modulo\n"
        "spec.loader.exec_module(modulo)\n"
        "print('STANDSALONE_OK')\n"
        "print('CON_APP' if 'app' in sys.modules else 'SIN_APP')\n"
        "print(modulo.RuntimeConnection('h', 3306, 'd', 'u', 'p'))\n"
    ) % (standalone / PYTHON_DUMP.name)

    completed = subprocess.run(
        # -E ignora PYTHONPATH: el checkout del repo no puede colarse en el
        # sys.path y hacer que el paquete app aparezca donde no debe.
        [sys.executable, "-E", "-c", codigo],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(standalone),
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "STANDSALONE_OK" in completed.stdout
    assert "SIN_APP" in completed.stdout
    assert "No module named" not in completed.stderr

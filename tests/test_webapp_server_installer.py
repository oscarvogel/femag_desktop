"""Pruebas del instalador del servidor webapp (#777).

El instalador es lo que va a correr el administrador de la fabrica: se escribe
la clave de MySQL en un asistente, se corre un .exe y el servidor queda
levantado, con arranque automatico y el firewall abierto. El camino es corto
pero no por eso deja de ser critico: si el archivo de configuracion que escribe
no es el que lee el servidor, la fabrica se queda sin servicio y el error
aparece en el celular, no en la pantalla del servidor.

Por eso las pruebas no miran solo el texto del script: lo ejecutan y comprueban
que la configuracion que deja escrita es exactamente la que el servidor lee
(``app.config.settings.load_settings``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer" / "FEMAG_Webapp_Server.iss"
INSTALL_SCRIPT = ROOT / "scripts" / "instalar_webapp_servidor.ps1"
BUILD_SCRIPT = ROOT / "scripts" / "build_webapp_server_installer.ps1"

WINDOWS_ONLY = pytest.mark.skipif(
    os.name != "nt", reason="El instalador es de Windows Server 2019."
)


def _run_installer(
    tmp_path: Path,
    *extra: str,
    db_user: str | None = "femag_test",
    db_password: str | None = "clave-de-prueba",
) -> subprocess.CompletedProcess:
    """Ejecuta el script de instalacion en modo sin servicio.

    En modo sin servicio no se registra la tarea ni se abre el firewall: se
    escribe la configuracion y el lanzador, que es lo que se puede verificar
    sin permisos de administrador.

    Las credenciales se pueden dejar sin pasar (``db_user=None``) para
    reproducir el camino del instalador, que las manda en un archivo.
    """
    install_root = tmp_path / "webapp"
    install_root.mkdir(parents=True, exist_ok=True)
    # El script exige que el ejecutable este en el raiz de instalacion.
    (install_root / "FEMAG Webapp Server.exe").write_bytes(b"stub")

    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(INSTALL_SCRIPT),
        "-InstallRoot",
        str(install_root),
        "-ConfigPath",
        str(tmp_path / "webapp.env"),
    ]
    if db_user is not None:
        command += ["-DbUser", db_user]
    if db_password is not None:
        command += ["-DbPassword", db_password]
    command += ["-SkipServiceSetup", *extra]

    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_installer_is_an_inno_setup_that_needs_administrator():
    content = INSTALLER.read_text(encoding="utf-8")

    # La tarea programada corre como SYSTEM y el firewall necesita privilegios.
    assert "PrivilegesRequired=admin" in content
    # Un AppId propio: si no, el instalador se confunde con el de escritorio.
    assert "3803817A-0DE7-46CD-81FA-2E72FCFFA676" in content


def test_installer_does_not_put_the_mysql_password_in_the_command_line():
    """La clave no puede quedar en la linea de comandos.

    La linea de comandos de un proceso es visible para cualquiera de la
    maquina. Por eso los datos viajan en un archivo temporal que el script
    lee y que el instalador borra al terminar.
    """
    content = INSTALLER.read_text(encoding="utf-8")

    assert "femag-webapp-params.txt" in content
    assert "-ParamsFile" in content
    assert "DbPassword=" in content
    # En los parametros del paso de Run no puede aparecer la clave.
    run_line = [line for line in content.splitlines() if line.startswith("Filename:") and "instalar_webapp" in line]
    assert run_line, "El instalador tiene que llamar al script de instalacion."
    for line in run_line:
        assert "DbPassword" not in line, line


def test_installer_can_be_driven_without_the_wizard():
    """Instalacion desatendida: los datos pueden venir por linea de comandos.

    Es lo que permite instalar sin que nadie tenga que tocar el asistente (y
    lo que hace posible automatizar la prueba en CI).
    """
    content = INSTALLER.read_text(encoding="utf-8")

    for parameter in ("HOST", "WEBPORT", "DBHOST", "DBPORT", "DBNAME", "DBUSER", "DBPASSWORD"):
        assert f"'{parameter}'" in content, parameter


def test_the_parameters_file_is_written_before_the_run_step():
    """El paso [Run] se ejecuta DESPUES de ssPostInstall.

    Con el archivo escrito en ssPostInstall, el instalador corria el script
    sin datos y la instalacion fallaba en la fabrica, donde no hay nadie para
    mirar la consola. El hook correcto es PrepareToInstall.
    """
    content = INSTALLER.read_text(encoding="utf-8")

    assert "function PrepareToInstall" in content
    prepare = content.split("function PrepareToInstall", 1)[1].split(
        "procedure CurStepChanged", 1
    )[0]
    assert "femag-webapp-params.txt" in prepare
    # UTF-8 con BOM: la clave de MySQL puede tener acentos y el script lo lee
    # con PowerShell 5.1, que sin BOM lee el archivo como Windows-1252.
    assert "SaveStringsToUTF8File" in prepare

    # Y el paso Run tiene que leer ese mismo archivo.
    assert '-ParamsFile ""{tmp}\\femag-webapp-params.txt""' in content


def test_uninstall_cleans_up_the_service_and_the_firewall_rule():
    content = INSTALLER.read_text(encoding="utf-8")

    assert "Unregister-ScheduledTask" in content
    assert "Remove-NetFirewallRule" in content
    # Sin RunOnceId, Inno Setup avisa y el paso se puede correr dos veces.
    assert "RunOnceId:" in content


def test_install_script_has_the_bom_that_powershell_5_1_needs():
    """Windows Server 2019 corre PowerShell 5.1.

    Un .ps1 sin BOM se lee como Windows-1252: los acentos se rompen y, si algun
    byte cae en el rango de las comillas tipograficas, el script deja de
    parsear y el servicio no arranca.
    """
    raw = INSTALL_SCRIPT.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf"), (
        "instalar_webapp_servidor.ps1 necesita BOM UTF-8 para PowerShell 5.1."
    )


def test_install_script_parses_in_powershell_5_1():
    """Un error de sintaxis en el script se descubre en la fabrica, no aca."""
    command = (
        "$t=$null; $e=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{INSTALL_SCRIPT}',[ref]$t,[ref]$e) | Out-Null; "
        "if ($e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


@WINDOWS_ONLY
def test_the_installation_leaves_a_log_of_what_it_did(tmp_path):
    """El administrador de la fabrica no ve la consola del instalador.

    Si algo falla, lo que hay que mirar es el log de la instalacion.
    """
    completed = _run_installer(tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr

    log = tmp_path / "logs" / "instalar_servidor.log"
    assert log.exists(), "La instalacion tiene que dejar log."
    contenido = log.read_text(encoding="utf-8", errors="replace")
    assert "Inicio de la instalacion" in contenido
    assert "Escribiendo la configuracion" in contenido
    # La clave de MySQL no puede quedar escrita en el log.
    assert "clave-de-prueba" not in contenido


def test_the_build_driver_exists_and_parses_in_powershell_5_1():
    """El driver es lo que genera el .exe que se copia a la fabrica."""
    assert BUILD_SCRIPT.exists()

    raw = BUILD_SCRIPT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), (
        "build_webapp_server_installer.ps1 necesita BOM UTF-8 para PowerShell 5.1."
    )

    command = (
        "$t=$null; $e=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{BUILD_SCRIPT}',[ref]$t,[ref]$e) | Out-Null; "
        "if ($e.Count -gt 0) { $e | ForEach-Object { $_.Message }; exit 1 }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_ci_compiles_the_installer():
    """Si el instalador no compila, el .exe de la fabrica no existe."""
    content = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "installer\\FEMAG_Webapp_Server.iss" in content
    assert "FEMAG_Webapp_Server_Setup.exe" in content


@WINDOWS_ONLY
def test_install_script_writes_the_configuration_and_the_launcher(tmp_path):
    completed = _run_installer(tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr

    config = (tmp_path / "webapp.env").read_text(encoding="utf-8-sig")
    assert "DB_USER=femag_test" in config
    assert "DB_PASSWORD=clave-de-prueba" in config
    assert "FEMAG_AUTO_MIGRATE_SCHEMA=0" in config
    # La URL del QR tiene que ser la que el celular puede abrir.
    assert "FEMAG_WEB_PUBLIC_URL=http://femag.lan:8000" in config
    # El secreto de sesion vive junto a la configuracion, no en el perfil de SYSTEM.
    assert "FEMAG_WEB_SECRET_FILE=" in config

    launcher = (tmp_path / "webapp" / "run_webapp.cmd").read_text(encoding="utf-8")
    assert 'set "FEMAG_WEB_HOST=0.0.0.0"' in launcher
    assert 'set "FEMAG_WEB_PORT=8000"' in launcher


@WINDOWS_ONLY
def test_launcher_has_no_bom_because_cmd_treats_it_as_a_command(tmp_path):
    """Un .cmd con BOM no arranca: cmd.exe ve el BOM como parte del comando."""
    completed = _run_installer(tmp_path)

    assert completed.returncode == 0, completed.stdout + completed.stderr

    raw = (tmp_path / "webapp" / "run_webapp.cmd").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")


@WINDOWS_ONLY
def test_reinstalling_does_not_wipe_the_configuration(tmp_path):
    """Si se pierde la configuracion hay que volver a escribir la clave.

    Y con ella se caen las sesiones abiertas. Una reinstalacion tiene que
    conservarla.
    """
    first = _run_installer(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr

    config_path = tmp_path / "webapp.env"
    config_path.write_text(
        config_path.read_text(encoding="utf-8-sig") + "# marca de la primera instalacion\n",
        encoding="utf-8-sig",
    )

    second = _run_installer(tmp_path)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "marca de la primera instalacion" in config_path.read_text(encoding="utf-8-sig")
    assert "La configuracion ya existe: se conserva" in second.stdout


@WINDOWS_ONLY
def test_the_configuration_written_is_the_one_the_server_reads(tmp_path, monkeypatch):
    """El archivo que escribe el instalador es el que lee el servidor.

    Es el punto de todo el instalador: si una clave cambia de nombre o el
    motor queda para otro lado, el servidor arranca con otra configuracion y
    en la fabrica se ve como que "no se conecta a la base".
    """
    completed = _run_installer(tmp_path, "-DbEngine", "mysql")
    assert completed.returncode == 0, completed.stdout + completed.stderr

    for variable in (
        "APP_ENV",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "FEMAG_DB_ENGINE",
        "FEMAG_AUTO_MIGRATE_SCHEMA",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("FEMAG_ENV_FILE", str(tmp_path / "webapp.env"))

    from app.config.settings import load_settings

    settings = load_settings()

    assert settings.db_engine == "mysql"
    assert settings.db_host == "127.0.0.1"
    assert settings.db_port == 3306
    assert settings.db_name == "femag_desktop"
    assert settings.db_user == "femag_test"
    assert settings.db_password == "clave-de-prueba"


@WINDOWS_ONLY
def test_the_installer_reads_the_data_from_a_file_and_not_from_the_arguments(tmp_path):
    """El camino que usa el instalador de verdad: los datos en un archivo.

    La clave viaja en un archivo temporal en vez de la linea de comandos.
    """
    params = tmp_path / "params.txt"
    params.write_text(
        "# Datos del servidor webapp de FEMAG (clave de MySQL)\n"
        "PublicHostName=femag.lan\n"
        "WebPort=8123\n"
        "DbHost=10.0.0.5\n"
        "DbPort=3307\n"
        "DbName=femag_fabrica\n"
        "DbUser=femag_webapp\n"
        "DbPassword=clave-de-la-fabrica\n",
        encoding="utf-8",
    )

    completed = _run_installer(
        tmp_path, "-ParamsFile", str(params), db_user=None, db_password=None
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr

    config = (tmp_path / "webapp.env").read_text(encoding="utf-8-sig")
    assert "DB_HOST=10.0.0.5" in config
    assert "DB_PORT=3307" in config
    assert "DB_NAME=femag_fabrica" in config
    assert "DB_USER=femag_webapp" in config
    assert "DB_PASSWORD=clave-de-la-fabrica" in config
    assert "FEMAG_WEB_PUBLIC_URL=http://femag.lan:8123" in config


@WINDOWS_ONLY
def test_a_wrong_database_engine_is_rejected(tmp_path):
    """Un motor desconocido tiene que cortar la instalacion, no el servicio."""
    completed = _run_installer(tmp_path, "-DbEngine", "postgres")

    assert completed.returncode != 0
    assert "DbEngine" in completed.stdout + completed.stderr
    assert not (tmp_path / "webapp.env").exists()

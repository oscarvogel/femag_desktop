"""El respaldo manual tiene que respaldar (#643).

Antes de este PR, ``BackupService._default_dump_runner`` escribia un texto que
decia "Configure mysqldump for production backups." y devolvia exito. El
operador se llevaba un ``.sql`` que no era un dump, ``BackupLog`` decia
``success`` y el dashboard mostraba "Ultimo backup: success".

Estos tests fijan las tres cosas que importan:

  1. el runner por default usa el motor de dump real;
  2. si el dump falla, la operacion falla y queda ``BackupLog.status == "error"``,
     nunca ``success``;
  3. la contrasena no aparece en el mensaje que queda guardado.

El punto 3 esta porque el mensaje de un ``mysqldump`` fallido va al log y a la
base, y una contrasena ahi es un incidente.
"""

import pytest

from app.config.settings import Settings
from app.services.backup_service import BackupService, _sin_password


def _settings_para_mysql():
    return Settings(
        app_env="test",
        db_engine="mysql",
        db_host="127.0.0.1",
        db_port=3306,
        db_name="femag_prueba",
        db_user="prueba",
        db_password="clave-secreta",
        sqlite_path="femag.sqlite3",
        demo=False,
        backup_dir="backups",
        backup_extra_dir=None,
        log_level="WARNING",
    )


@pytest.fixture()
def servicio(db, tmp_path, monkeypatch):
    """BackupService con los settings de MySQL y sin config segura del puesto.

    El monkeypatch va a ``app.services.backup_service.load_settings`` y no a
    ``app.config.settings``: el servicio captura la funcion al importarse, asi
    que parchear el modulo de origen no alcanza.
    """
    monkeypatch.delenv("FEMAG_SECURE_CONFIG", raising=False)
    monkeypatch.setattr(
        "app.services.backup_service.load_settings", lambda: _settings_para_mysql()
    )
    monkeypatch.setattr(
        "app.config.settings.resolve_effective_connection_settings", lambda **_kwargs: False
    )
    return BackupService(backup_dir=tmp_path, extra_dir=None)


def test_el_runner_por_default_usa_el_motor_de_dump_real(servicio, tmp_path, monkeypatch):
    """Nada de escribir texto: se llama al motor de dump con la conexion real."""
    from pathlib import Path as _Path

    from app.models.system import BackupLog
    from app.services import mysql_dump

    vistos = {}

    def runner_falso(connection, database, destination):
        vistos["connection"] = connection
        vistos["database"] = database
        destination.write_text("-- dump de verdad\nCREATE TABLE `budget` (`id` int);\n",
                               encoding="utf-8")
        return mysql_dump.DatabaseDump(database, str(destination), "success")

    monkeypatch.setattr(mysql_dump, "pick_dump_runner", lambda **_kwargs: runner_falso)

    servicio.run_manual_backup(user="operador1")

    assert vistos["database"] == "femag_prueba"
    assert vistos["connection"].password == "clave-secreta"

    # El nombre del archivo lo pone el servicio (con timestamp), asi que la ruta
    # real se lee del BackupLog y no del tmp_path.
    log = BackupLog.select().order_by(BackupLog.id.desc()).first()
    destino = _Path(log.file_path)
    assert destino.exists()
    contenido = destino.read_text(encoding="utf-8")
    assert "CREATE TABLE" in contenido
    assert "Configure mysqldump" not in contenido


def test_el_servicio_no_inventa_el_archivo_si_no_hubo_dump(servicio, tmp_path, monkeypatch):
    """Si el motor no escribio, no hay archivo. Y no hay nota de configuracion.

    Este es el test que detecta el bug. Con el stub viejo, el servicio escribia
    "Configure mysqldump for production backups." siempre, mas o menos al margen
    de si hubo dump o no; aca se verifica lo contrario: el servicio no tiene
    logica de escritura propia, delega en el motor, y no aparece ningun archivo
    con una nota de configuracion.
    """
    from pathlib import Path as _Path

    from app.models.system import BackupLog
    from app.services import mysql_dump

    monkeypatch.setattr(
        mysql_dump, "pick_dump_runner",
        lambda **_kwargs: (lambda connection, database, destination: mysql_dump.DatabaseDump(
            database, str(destination), "success")),
    )

    servicio.run_manual_backup(user="operador1")

    log = BackupLog.select().order_by(BackupLog.id.desc()).first()
    destino = _Path(log.file_path)
    assert not destino.exists(), (
        "el servicio no debe crear el archivo por si mismo: si no hubo dump, no hay dump"
    )
    leftovers = list(tmp_path.glob("*.sql"))
    assert leftovers == [], "no debe quedar ningun .sql: %s" % leftovers
    assert not any(
        "Configure mysqldump" in path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.glob("*") if path.is_file()
    ), "no debe aparecer la nota de configuracion en ningun archivo"


def test_si_el_dump_falla_la_operacion_falla_y_no_dice_success(servicio, tmp_path, monkeypatch):
    """Un respaldo que no se pudo hacer tiene que quedar como error."""
    from app.services import mysql_dump
    from app.models.system import BackupLog

    destino = tmp_path / "femag-backup.sql"
    monkeypatch.setattr(
        mysql_dump, "pick_dump_runner",
        lambda **_kwargs: (lambda connection, database, destination: mysql_dump.DatabaseDump(
            database, None, "error", "mysqldump: no se pudo conectar")),
    )

    with pytest.raises(RuntimeError):
        servicio.run_manual_backup(user="operador1")

    log = BackupLog.select().order_by(BackupLog.id.desc()).first()
    assert log is not None
    assert log.status == "error"
    assert "no se pudo conectar" in log.message


def test_si_el_engine_no_es_mysql_no_se_escribe_nada(servicio, tmp_path, monkeypatch):
    """Sin MySQL configurado, no hay respaldo: hay un error."""
    from app.config.settings import Settings

    sqlite_settings = Settings(
        app_env="test", db_engine="sqlite", db_host="", db_port=0, db_name="",
        db_user="", db_password="", sqlite_path=str(tmp_path / "demo.sqlite3"),
        demo=True, backup_dir=str(tmp_path), backup_extra_dir=None, log_level="WARNING",
    )
    monkeypatch.setattr("app.services.backup_service.load_settings", lambda: sqlite_settings)

    destino = tmp_path / "femag-backup.sql"
    with pytest.raises(RuntimeError) as error:
        servicio._default_dump_runner(destino)

    assert "mysql" in str(error.value).lower()
    assert not destino.exists(), "no debe quedar ningun archivo de un respaldo que no ocurrio"


def test_la_contrasena_no_aparece_en_el_mensaje_que_se_guarda():
    """El mensaje de error va al log y a la base: la contrasena no puede ir."""
    sucio = "Fallo el respaldo: access denied for user 'u' using password 'clave-secreta'"

    limpio = _sin_password(sucio, "clave-secreta")

    assert "clave-secreta" not in limpio
    assert "***" in limpio


def test_la_contrasena_tampoco_aparece_cuando_el_dump_falla(servicio, tmp_path, monkeypatch):
    """La defensa de punta a punta: el mensaje de mysqldump tampoco la filtra."""
    from app.services import mysql_dump

    monkeypatch.setattr(
        mysql_dump, "pick_dump_runner",
        lambda **_kwargs: (lambda connection, database, destination: mysql_dump.DatabaseDump(
            database, None, "error",
            "error 1045: using password 'clave-secreta' (NO)")))

    with pytest.raises(RuntimeError) as error:
        servicio._default_dump_runner(tmp_path / "femag-backup.sql")

    assert "clave-secreta" not in str(error.value)

from pathlib import Path

from peewee import MySQLDatabase, SqliteDatabase


def test_settings_load_defaults_and_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=testing\nDB_HOST=db.local\nDB_PORT=3307\nDB_NAME=femag_test\n"
        "BACKUP_DIR=C:/backups\nBACKUP_EXTRA_DIR=//server/copia\n"
        "FEMAG_DB_ENGINE=mysql\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FEMAG_ENV_FILE", str(env_file))

    from app.config.settings import load_settings

    settings = load_settings()

    assert settings.app_env == "testing"
    assert settings.db_host == "db.local"
    assert settings.db_port == 3307
    assert settings.db_name == "femag_test"
    assert settings.db_engine == "mysql"
    assert settings.sqlite_path == Path("femag_demo.sqlite3")
    assert settings.demo is False
    assert settings.backup_dir == Path("C:/backups")
    assert settings.backup_extra_dir == Path("//server/copia")


def test_initialize_runtime_database_uses_sqlite_when_demo_env_requests_it(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    sqlite_path = tmp_path / "femag_demo.sqlite3"
    env_file.write_text(
        f"FEMAG_DB_ENGINE=sqlite\nFEMAG_SQLITE_PATH={sqlite_path}\nFEMAG_DEMO=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FEMAG_ENV_FILE", str(env_file))

    from app.config.database import initialize_runtime_database

    database = initialize_runtime_database()

    assert isinstance(database, SqliteDatabase)
    assert Path(database.database) == sqlite_path


def test_initialize_runtime_database_keeps_mysql_as_default(monkeypatch, tmp_path):
    # Apuntamos FEMAG_ENV_FILE a un archivo inexistente para que load_dotenv
    # sea un no-op y el resultado dependa sólo de las defaults, no del
    # `.env` que el dev tenga en el CWD.
    missing_env = tmp_path / "missing.env"
    monkeypatch.setenv("FEMAG_ENV_FILE", str(missing_env))
    monkeypatch.delenv("FEMAG_DB_ENGINE", raising=False)
    monkeypatch.delenv("FEMAG_DEMO", raising=False)

    from app.config.database import initialize_runtime_database

    database = initialize_runtime_database()

    assert isinstance(database, MySQLDatabase)


def test_mysql_hostname_is_resolved_to_ipv4_without_changing_settings(monkeypatch):
    from app.config import database as database_config
    from app.config.settings import Settings

    settings = Settings(
        app_env="testing",
        db_engine="mysql",
        db_host="almanet-server",
        db_port=3306,
        db_name="femag_desktop",
        db_user="puesto",
        db_password="secreta",
        sqlite_path=Path("unused.sqlite3"),
        demo=False,
        backup_dir=Path("backups"),
        backup_extra_dir=None,
        log_level="INFO",
    )
    monkeypatch.setattr(database_config.socket, "gethostbyname", lambda host: "192.168.0.116")

    database = database_config.build_mysql_database(settings)

    assert settings.db_host == "almanet-server"
    assert database.connect_params["host"] == "192.168.0.116"


def test_database_can_bind_sqlite_for_tests(db):
    from app.models.security import UserProfile

    profile = UserProfile.create(name="Administrador", description="Acceso total")

    assert profile.id is not None

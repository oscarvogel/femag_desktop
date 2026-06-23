from pathlib import Path


def test_settings_load_defaults_and_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=testing\nDB_HOST=db.local\nDB_PORT=3307\nDB_NAME=femag_test\n"
        "BACKUP_DIR=C:/backups\nBACKUP_EXTRA_DIR=//server/copia\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FEMAG_ENV_FILE", str(env_file))

    from app.config.settings import load_settings

    settings = load_settings()

    assert settings.app_env == "testing"
    assert settings.db_host == "db.local"
    assert settings.db_port == 3307
    assert settings.db_name == "femag_test"
    assert settings.backup_dir == Path("C:/backups")
    assert settings.backup_extra_dir == Path("//server/copia")


def test_database_can_bind_sqlite_for_tests(db):
    from app.models.security import UserProfile

    profile = UserProfile.create(name="Administrador", description="Acceso total")

    assert profile.id is not None

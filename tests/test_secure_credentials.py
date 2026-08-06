import json

import pytest


def test_runtime_connection_is_split_and_password_is_not_plaintext(tmp_path, monkeypatch):
    from app.config import secure_credentials
    from app.config.secure_credentials import RuntimeConnection

    monkeypatch.setattr(secure_credentials, "protect_password", lambda value: b"dpapi:" + value[::-1].encode())
    monkeypatch.setattr(
        secure_credentials,
        "unprotect_password",
        lambda value: value.removeprefix(b"dpapi:")[::-1].decode(),
    )
    connection = RuntimeConnection("mysql.lan", 3306, "femag_test", "puesto", "muy-secreta")

    secure_credentials.save_runtime_connection(connection, tmp_path)

    config_text = (tmp_path / "connection.json").read_text(encoding="utf-8")
    credential = (tmp_path / "connection.credential").read_bytes()
    assert json.loads(config_text) == {
        "version": 1,
        "host": "mysql.lan",
        "port": 3306,
        "database": "femag_test",
        "user": "puesto",
    }
    assert "muy-secreta" not in config_text
    assert b"muy-secreta" not in credential
    assert secure_credentials.load_runtime_connection(tmp_path) == connection


def test_invalid_or_missing_local_configuration_requests_reconfiguration(tmp_path):
    from app.config.secure_credentials import SecureConfigurationError, load_runtime_connection

    with pytest.raises(SecureConfigurationError, match="todavia no esta configurada"):
        load_runtime_connection(tmp_path)


def test_secure_configuration_overrides_plaintext_database_environment(tmp_path, monkeypatch):
    from app.config import secure_credentials
    from app.config.secure_credentials import RuntimeConnection

    monkeypatch.setattr(secure_credentials, "protect_password", lambda _value: b"encrypted")
    monkeypatch.setattr(secure_credentials, "unprotect_password", lambda _value: "dpapi-password")
    monkeypatch.setattr(secure_credentials, "default_config_dir", lambda: tmp_path)
    secure_credentials.save_runtime_connection(
        RuntimeConnection("mysql.secure", 3307, "femag_secure", "puesto_secure", "ignored"),
        tmp_path,
    )
    monkeypatch.setenv("FEMAG_SECURE_CONFIG", "1")
    monkeypatch.setenv("DB_PASSWORD", "texto-plano-que-no-debe-usarse")

    from app.config.settings import load_settings

    settings = load_settings()

    assert settings.db_host == "mysql.secure"
    assert settings.db_port == 3307
    assert settings.db_name == "femag_secure"
    assert settings.db_user == "puesto_secure"
    assert settings.db_password == "dpapi-password"


def test_runtime_connection_requires_all_fields():
    from app.config.secure_credentials import RuntimeConnection

    with pytest.raises(ValueError, match="contrasena"):
        RuntimeConnection("mysql.lan", 3306, "femag", "puesto", "").validate()


def test_connection_dialog_masks_tests_and_saves_password(monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit

    from app.ui import connection_dialog

    qt_app = QApplication.instance() or QApplication([])
    calls = []
    monkeypatch.setattr(
        connection_dialog,
        "test_runtime_connection",
        lambda connection: calls.append(("test", connection)),
    )
    monkeypatch.setattr(
        connection_dialog,
        "save_runtime_connection",
        lambda connection: calls.append(("save", connection)),
    )
    dialog = connection_dialog.ConnectionDialog()
    dialog.host.setText("mysql.lan")
    dialog.database.setText("femag_pruebas")
    dialog.user.setText("puesto")
    dialog.password.setText("secreta")

    assert dialog.password.echoMode() == QLineEdit.Password
    dialog._test_and_save()

    assert dialog.result() == QDialog.Accepted
    assert [action for action, _connection in calls] == ["test", "save"]
    assert calls[1][1].password == "secreta"


def test_connection_test_reports_mysql_error_code(monkeypatch):
    from peewee import OperationalError

    from app.config.secure_credentials import RuntimeConnection
    from app.ui import connection_dialog

    class RejectedDatabase:
        def connect(self):
            raise OperationalError(1045, "Access denied for user")

        def is_closed(self):
            return True

    monkeypatch.setattr(connection_dialog, "build_mysql_database", lambda _settings: RejectedDatabase())

    with pytest.raises(RuntimeError, match=r"MySQL rechazo la conexion \(1045\)"):
        connection_dialog.test_runtime_connection(
            RuntimeConnection("mysql.lan", 3306, "femag", "puesto", "secreta")
        )

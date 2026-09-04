from __future__ import annotations

from peewee import InterfaceError, OperationalError
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from app.build_version import BUILD_VERSION
from app.config.database import (
    build_mysql_database,
    ensure_mysql_database_exists,
    initialize_runtime_database,
)
from app.config.schema import SchemaValidationError, validate_runtime_schema
from app.config.schema import ensure_runtime_schema
from app.config.secure_credentials import (
    RuntimeConnection,
    SecureConfigurationError,
    has_runtime_configuration,
    load_runtime_connection,
    save_runtime_connection,
)
from app.config.settings import Settings


DEFAULT_MYSQL_HOST = "almanet-server"
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_DATABASE = "femag_desktop"


class RuntimeSchemaPreparationRequired(RuntimeError):
    pass


class ConnectionDialog(QDialog):
    def __init__(self, *, current: RuntimeConnection | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"FEMAG Desktop {BUILD_VERSION} - Conexion MySQL")
        self.setMinimumWidth(470)
        self._current = current

        self.host = QLineEdit(current.host if current else DEFAULT_MYSQL_HOST)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(current.port if current else DEFAULT_MYSQL_PORT)
        self.database = QLineEdit(current.database if current else DEFAULT_MYSQL_DATABASE)
        self.user = QLineEdit(current.user if current else "")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        if current is not None:
            self.password.setPlaceholderText("Dejar vacio para mantener la clave guardada")

        intro = QLabel(
            "Configure una sola vez el acceso operativo a MySQL. La contrasena se cifra "
            "con Windows y solamente puede recuperarla este usuario de Windows."
        )
        intro.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Servidor:", self.host)
        form.addRow("Puerto:", self.port)
        form.addRow("Base de datos:", self.database)
        form.addRow("Usuario:", self.user)
        form.addRow("Contrasena:", self.password)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Probar y guardar")
        self.buttons.accepted.connect(self._test_and_save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

    def connection(self) -> RuntimeConnection:
        password = self.password.text()
        if not password and self._current is not None:
            password = self._current.password
        return RuntimeConnection(
            host=self.host.text(),
            port=self.port.value(),
            database=self.database.text(),
            user=self.user.text(),
            password=password,
        )

    def _test_and_save(self) -> None:
        connection = self.connection()
        try:
            connection.validate()
            test_runtime_connection(connection)
        except RuntimeSchemaPreparationRequired as exc:
            answer = QMessageBox.question(
                self,
                "Preparar base de datos",
                f"{exc}\n\n¿Crear o actualizar ahora las tablas de FEMAG? "
                "Esta accion requiere un usuario MySQL administrador.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                prepare_runtime_schema(connection)
            except RuntimeError as prepare_exc:
                QMessageBox.critical(
                    self, "No se pudo preparar la base de datos", str(prepare_exc)
                )
                return
        except (ValueError, RuntimeError, SecureConfigurationError) as exc:
            QMessageBox.critical(self, "No se pudo guardar la conexion", str(exc))
            return
        try:
            save_runtime_connection(connection)
        except SecureConfigurationError as exc:
            QMessageBox.critical(self, "No se pudo guardar la conexion", str(exc))
            return
        self.accept()


def _settings_for_connection(connection: RuntimeConnection) -> Settings:
    from pathlib import Path

    return Settings(
        app_env="production",
        db_engine="mysql",
        db_host=connection.host.strip(),
        db_port=connection.port,
        db_name=connection.database.strip(),
        db_user=connection.user.strip(),
        db_password=connection.password,
        sqlite_path=Path("femag_demo.sqlite3"),
        demo=False,
        backup_dir=Path("backups"),
        backup_extra_dir=None,
        log_level="INFO",
    )


def test_runtime_connection(connection: RuntimeConnection) -> None:
    database = build_mysql_database(_settings_for_connection(connection))
    try:
        database.connect()
        validate_runtime_schema(database)
    except SchemaValidationError as exc:
        raise RuntimeSchemaPreparationRequired(
            f"La base existe pero su estructura no es compatible: {exc}. "
            "Debe prepararse antes de usar este puesto."
        ) from exc
    except (OperationalError, InterfaceError) as exc:
        code, message = _mysql_error_detail(exc)
        if str(code) == "1049":
            raise RuntimeSchemaPreparationRequired(
                f"La base de datos '{connection.database}' no existe. "
                "Se creara y se generaran todas las tablas con el usuario administrador."
            ) from exc
        raise RuntimeError(
            f"MySQL rechazo la conexion ({code}): {message}"
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo iniciar el cliente MySQL ({type(exc).__name__})."
        ) from exc
    finally:
        if not database.is_closed():
            database.close()


def _mysql_error_detail(exc: Exception) -> tuple[str, str]:
    args = getattr(exc, "args", ())
    code = str(args[0]) if args else "sin codigo"
    message = str(args[1]) if len(args) > 1 else str(exc)
    return code, message or "sin detalle"


def prepare_runtime_schema(connection: RuntimeConnection) -> None:
    settings = _settings_for_connection(connection)
    # Si la base no existe (error 1049), crearla antes de conectar con peewee.
    try:
        ensure_mysql_database_exists(settings)
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo crear la base de datos '{settings.db_name}' ({type(exc).__name__}): {exc}"
        ) from exc
    database = initialize_runtime_database(settings)
    try:
        database.connect(reuse_if_open=True)
        ensure_runtime_schema(database)
        validate_runtime_schema(database)
        # Asegura perfiles/permisos base para el primer admin (bootstrap login)
        try:
            from app.services.permission_service import PermissionService

            PermissionService().seed_defaults()
        except Exception:
            pass
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo crear o actualizar la estructura ({type(exc).__name__}): {exc}"
        ) from exc
    finally:
        if not database.is_closed():
            database.close()


def ensure_runtime_configuration(*, force: bool = False, parent=None) -> bool:
    # Una actualización del programa no debe volver a pedir la conexión si ya
    # existe la configuración segura del puesto. La validación operativa de
    # MySQL se realiza luego al abrir la aplicación; este diálogo queda
    # reservado para la primera configuración o para --configure explícito.
    if not force and has_runtime_configuration():
        return True

    current = None
    if force:
        try:
            current = load_runtime_connection()
        except SecureConfigurationError:
            pass
    return ConnectionDialog(current=current, parent=parent).exec_() == QDialog.Accepted

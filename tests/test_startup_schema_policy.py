"""Politica de migracion del arranque (#660).

El arranque de los puestos es read-only respecto del esquema: el estado de la base
compartida no puede depender de que puesto abre primero. La migracion la aplica un
administrador, por el asistente de conexion o por `scripts/init_db.py`.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeDatabase:
    """Doble de MySQLDatabase que registra si alguien intento migrar."""

    instances = []

    def __init__(self, *_args, **_kwargs):
        self.migrated = False
        self.connected = False
        type(self).instances.append(self)

    def connect(self, *args, **kwargs):
        self.connected = True
        return self

    def close(self):
        pass

    def is_closed(self):
        return not self.connected


@pytest.fixture()
def spy_migrations(monkeypatch):
    """Reemplaza ensure_runtime_schema por un espia y devuelve la lista de llamadas.

    El import de `ensure_runtime_schema` ocurre dentro de `connect`, asi que
    parchear el modulo alcanza.
    """
    calls = []

    import app.config.schema as schema_module
    from app.services.client_payment_service import ClientPaymentService

    monkeypatch.setattr(schema_module, "ensure_runtime_schema", calls.append)
    # El resto del bloque siembra medios de pago y tocaria una base real: aca no
    # interesa, lo que se mide es si se decide migrar.
    monkeypatch.setattr(
        ClientPaymentService, "ensure_default_payment_methods", staticmethod(list)
    )
    return calls


def _database(monkeypatch):
    """FemagMySQLDatabase real con el connect de peewee neutralizado.

    Se ejercita el override de `connect` (que es lo que decide si migra) sin
    necesitar un MySQL.
    """
    from app.config import database as database_module

    monkeypatch.setattr(
        database_module.MySQLDatabase, "connect", lambda self, *a, **k: self
    )
    return database_module.FemagMySQLDatabase(
        "femag_desktop", user="operador", password="clave", host="almanet-server"
    )


def test_startup_does_not_migrate_the_shared_schema_by_default(monkeypatch, spy_migrations):
    """El puesto que abre NO debe decidir el esquema de la base compartida."""
    monkeypatch.delenv("FEMAG_AUTO_MIGRATE_SCHEMA", raising=False)

    _database(monkeypatch).connect()

    assert spy_migrations == []


def test_auto_migrate_is_still_available_for_a_supervised_window(monkeypatch, spy_migrations):
    """La emergencia documentada sigue existiendo, pero es explicita."""
    monkeypatch.setenv("FEMAG_AUTO_MIGRATE_SCHEMA", "1")

    database = _database(monkeypatch)
    database.connect()

    assert spy_migrations == [database]


def test_deploy_doc_still_describes_read_only_startup():
    """El codigo y `DEPLOY.md` tienen que decir lo mismo."""
    from pathlib import Path

    content = (Path(__file__).resolve().parents[1] / "DEPLOY.md").read_text(
        encoding="utf-8"
    )

    assert "Los arranques normales siguen siendo read-only" in content
    assert "Ventana de mantenimiento antes de promover un build con cambios de esquema" in content


def test_admin_preparation_still_seeds_payment_methods(monkeypatch):
    """Con el arranque read-only, la preparacion del admin es la que crea los medios.

    Antes los creaba el arranque de cada puesto, dentro del mismo bloque que
    migraba. Al apagar ese bloque, la preparacion tiene que cubrirlos o una base
    nueva queda sin medios de pago.
    """
    from app.ui import connection_dialog

    calls = []

    class _Database:
        def connect(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def is_closed(self):
            return False

    monkeypatch.setattr(connection_dialog, "ensure_mysql_database_exists", lambda settings: None)
    monkeypatch.setattr(connection_dialog, "initialize_runtime_database", lambda settings: _Database())
    monkeypatch.setattr(connection_dialog, "ensure_runtime_schema", lambda database: calls.append("schema"))
    monkeypatch.setattr(connection_dialog, "validate_runtime_schema", lambda database: calls.append("validate"))
    monkeypatch.setattr(
        connection_dialog,
        "PermissionService",
        None,
        raising=False,
    )

    from app.services.client_payment_service import ClientPaymentService

    monkeypatch.setattr(
        ClientPaymentService,
        "ensure_default_payment_methods",
        staticmethod(lambda: calls.append("pagos")),
    )

    connection = connection_dialog.RuntimeConnection(
        host="almanet-server",
        port=3306,
        database="femag_desktop",
        user="admin",
        password="clave",
    )

    connection_dialog.prepare_runtime_schema(connection)

    assert calls == ["schema", "validate", "pagos"]
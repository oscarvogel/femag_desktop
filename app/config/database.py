import os
import socket

from peewee import DatabaseProxy, MySQLDatabase, SqliteDatabase

from app.config.settings import Settings, load_settings


database_proxy = DatabaseProxy()


class FemagMySQLDatabase(MySQLDatabase):
    """MySQL con preparación idempotente del esquema al abrir la aplicación.

    `ensure_runtime_schema()` usa CREATE TABLE safe / ALTER sólo para faltantes, por
    lo que una versión nueva puede incorporar tablas/columnas sin intervención en
    cada puesto. Puede desactivarse con FEMAG_AUTO_MIGRATE_SCHEMA=0 si se necesita
    una ventana de mantenimiento administrada.
    """

    def connect(self, *args, **kwargs):
        result = super().connect(*args, **kwargs)
        if (
            os.getenv("FEMAG_AUTO_MIGRATE_SCHEMA", "1") != "0"
            and not getattr(self, "_femag_schema_prepared", False)
        ):
            from app.config.schema import ensure_runtime_schema
            from app.services.client_payment_service import ClientPaymentService

            ensure_runtime_schema(self)
            ClientPaymentService.ensure_default_payment_methods()
            self._femag_schema_prepared = True
        return result


def resolve_mysql_host_ipv4(host: str) -> str:
    """Resolve a DNS/NetBIOS server name to IPv4 without changing saved configuration."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


def build_mysql_database(settings: Settings | None = None) -> MySQLDatabase:
    settings = settings or load_settings()
    return FemagMySQLDatabase(
        settings.db_name,
        host=resolve_mysql_host_ipv4(settings.db_host),
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
    )


def ensure_mysql_database_exists(settings: Settings | None = None) -> None:
    """Crea la base MySQL si no existe (permite primer inicio sin DB)."""
    settings = settings or load_settings()
    if settings.db_engine != "mysql":
        return
    # Conexión sin base para poder ejecutar CREATE DATABASE
    import pymysql

    host = resolve_mysql_host_ipv4(settings.db_host)
    conn = pymysql.connect(
        host=host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        db_name = settings.db_name.strip().replace("`", "``")
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
    finally:
        conn.close()


def build_sqlite_database(settings: Settings | None = None) -> SqliteDatabase:
    settings = settings or load_settings()
    sqlite_path = settings.sqlite_path
    if sqlite_path.parent != sqlite_path:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteDatabase(str(sqlite_path), pragmas={"foreign_keys": 1})


def build_runtime_database(settings: Settings | None = None):
    settings = settings or load_settings()
    if settings.db_engine == "sqlite":
        return build_sqlite_database(settings)
    return build_mysql_database(settings)


def bind_database(database) -> None:
    if database_proxy.obj is not None:
        database_proxy.initialize(database)
    else:
        database_proxy.initialize(database)


def initialize_runtime_database(settings: Settings | None = None):
    db = build_runtime_database(settings)
    bind_database(db)
    return db


def initialize_demo_database(settings: Settings | None = None):
    db = build_sqlite_database(settings)
    bind_database(db)
    return db

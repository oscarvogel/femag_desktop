from peewee import DatabaseProxy, MySQLDatabase, SqliteDatabase

from app.config.settings import Settings, load_settings


database_proxy = DatabaseProxy()


def build_mysql_database(settings: Settings | None = None) -> MySQLDatabase:
    settings = settings or load_settings()
    return MySQLDatabase(
        settings.db_name,
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
    )


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

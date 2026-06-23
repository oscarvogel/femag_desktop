from peewee import DatabaseProxy, MySQLDatabase

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


def bind_database(database) -> None:
    if database_proxy.obj is not None:
        database_proxy.initialize(database)
    else:
        database_proxy.initialize(database)


def initialize_runtime_database(settings: Settings | None = None):
    db = build_mysql_database(settings)
    bind_database(db)
    return db

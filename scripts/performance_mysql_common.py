from __future__ import annotations

import os
import re
from dataclasses import dataclass

import pymysql
from peewee import MySQLDatabase

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema


@dataclass(frozen=True)
class PerformanceDbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def performance_db_config(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> PerformanceDbConfig:
    config = PerformanceDbConfig(
        host=(host or os.getenv("DB_HOST") or "127.0.0.1").strip(),
        port=int(port or os.getenv("DB_PORT") or 3306),
        user=(user or os.getenv("DB_USER") or "femag").strip(),
        password=password if password is not None else os.getenv("DB_PASSWORD", ""),
        database=(database or os.getenv("FEMAG_PERFORMANCE_DB") or "femag_performance").strip(),
    )
    assert_safe_performance_database(config.database)
    return config


def assert_safe_performance_database(database: str) -> None:
    normalized = (database or "").strip().lower()
    if "performance" not in normalized:
        raise ValueError(
            "La base de performance debe contener 'performance' en su nombre. "
            "Ejemplo: femag_performance."
        )
    if not re.fullmatch(r"[A-Za-z0-9_]+", database or ""):
        raise ValueError("El nombre de la DB de performance contiene caracteres no permitidos.")
    if normalized in {"femag", "femag_prod", "production", "produccion"}:
        raise ValueError("Se rechazo una base potencialmente productiva.")


def ensure_mysql_database(config: PerformanceDbConfig, *, reset: bool = False) -> None:
    assert_safe_performance_database(config.database)
    connection = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            if reset:
                cursor.execute(f"DROP DATABASE IF EXISTS {config.database}")
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS {config.database} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
    finally:
        connection.close()


def connect_performance_database(config: PerformanceDbConfig) -> MySQLDatabase:
    assert_safe_performance_database(config.database)
    database = MySQLDatabase(
        config.database,
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        charset="utf8mb4",
    )
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    return database

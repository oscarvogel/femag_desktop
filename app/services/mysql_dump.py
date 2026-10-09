"""Dump SQL portable de una base MySQL, sin depender de las herramientas cliente.

Vive en ``app/`` y no en ``scripts/`` por una razón concreta: la aplicación
congelada de producción **no tiene Python ni el repositorio**. Si una tarea de
actualización necesita respaldar antes de alterar el esquema, tiene que poder
hacerlo desde la app instalada, no desde un script que existe sólo en el repo.

``scripts/backup_mysql_databases.py`` importa de acá: una sola implementación.

La contraseña nunca viaja en la línea de comandos ni entra en el archivo de
salida: en el caso de ``mysqldump`` va por ``MYSQL_PWD`` y en el caso puro
Python se usa la conexión ya abierta.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pymysql

from app.config.secure_credentials import RuntimeConnection

SYSTEM_DATABASES = frozenset({"information_schema", "mysql", "performance_schema", "sys"})


@dataclass(frozen=True)
class DatabaseDump:
    database: str
    file_path: str | None
    status: str
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success" and bool(self.file_path)


def safe_database_filename(database: str) -> str:
    """Nombre de archivo portable y determinista, sin alterar el nombre real."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", database).strip("._")
    return safe_name or "database"


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def accessible_databases(connection: RuntimeConnection) -> list[str]:
    """Bases no sistémicas visibles para el usuario MySQL configurado."""
    db = pymysql.connect(
        host=connection.host,
        port=connection.port,
        user=connection.user,
        password=connection.password,
        charset="utf8mb4",
    )
    try:
        with db.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            return sorted(
                row[0]
                for row in cursor.fetchall()
                if row[0].lower() not in SYSTEM_DATABASES
            )
    finally:
        db.close()


def _show_create(cursor, statement: str) -> str:
    cursor.execute(statement)
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"No se pudo obtener la definicion para: {statement}")
    for column, value in zip(cursor.description, row):
        if column[0].startswith("Create "):
            return value
    raise RuntimeError(f"La definicion recibida no tiene SQL CREATE: {statement}")


def _write_delimited_create(output, statement: str) -> None:
    """Procedimientos, eventos y triggers para el parser de la consola MySQL."""
    output.write("DELIMITER ;;\n")
    output.write(f"{statement};;\n")
    output.write("DELIMITER ;\n")


def dump_database_with_python(
    connection: RuntimeConnection,
    database: str,
    destination: Path,
    *,
    mysqldump_path: str | None = None,
) -> DatabaseDump:
    """Dump SQL portable sin depender de ``mysqldump``.

    Lee dentro de una transacción REPEATABLE READ con snapshot consistente, y
    publica el archivo de forma atómica: si algo falla, no queda un dump
    truncado que alguien pueda restaurar por error.
    """
    del mysqldump_path
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    database_identifier = quote_identifier(database)
    db = None
    try:
        db = pymysql.connect(
            host=connection.host,
            port=connection.port,
            user=connection.user,
            password=connection.password,
            database=database,
            charset="utf8mb4",
            autocommit=False,
        )
        with temporary.open("x", encoding="utf-8", newline="\n") as output, db.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            output.write("/*!40101 SET NAMES utf8mb4 */;\n")
            output.write("SET FOREIGN_KEY_CHECKS=0;\n")
            output.write(f"CREATE DATABASE IF NOT EXISTS {database_identifier};\n")
            output.write(f"USE {database_identifier};\n\n")

            cursor.execute(f"SHOW FULL TABLES FROM {database_identifier}")
            objects = cursor.fetchall()
            tables = [row[0] for row in objects if row[1] == "BASE TABLE"]
            views = [row[0] for row in objects if row[1] == "VIEW"]

            for table in tables:
                qualified = f"{database_identifier}.{quote_identifier(table)}"
                output.write(f"DROP TABLE IF EXISTS {qualified};\n")
                output.write(f"{_show_create(cursor, f'SHOW CREATE TABLE {qualified}')};\n")

            for table in tables:
                qualified = f"{database_identifier}.{quote_identifier(table)}"
                cursor.execute(f"SELECT * FROM {qualified}")
                placeholder = "(" + ", ".join(["%s"] * len(cursor.description)) + ")"
                for row in cursor:
                    output.write(
                        f"INSERT INTO {qualified} VALUES {cursor.mogrify(placeholder, row)};\n"
                    )

            for view in views:
                qualified = f"{database_identifier}.{quote_identifier(view)}"
                output.write(f"DROP VIEW IF EXISTS {qualified};\n")
                output.write(f"{_show_create(cursor, f'SHOW CREATE VIEW {qualified}')};\n")

            cursor.execute("SHOW TRIGGERS FROM " + database_identifier)
            for trigger in cursor.fetchall():
                identifier = f"{database_identifier}.{quote_identifier(trigger[0])}"
                output.write(f"DROP TRIGGER IF EXISTS {identifier};\n")
                _write_delimited_create(
                    output, _show_create(cursor, f"SHOW CREATE TRIGGER {identifier}")
                )

            cursor.execute(
                "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = %s ORDER BY ROUTINE_TYPE, ROUTINE_NAME",
                (database,),
            )
            for routine_name, routine_type in cursor.fetchall():
                identifier = f"{database_identifier}.{quote_identifier(routine_name)}"
                output.write(f"DROP {routine_type} IF EXISTS {identifier};\n")
                _write_delimited_create(
                    output, _show_create(cursor, f"SHOW CREATE {routine_type} {identifier}")
                )

            cursor.execute(f"SHOW EVENTS FROM {database_identifier}")
            for event in cursor.fetchall():
                identifier = f"{database_identifier}.{quote_identifier(event[0])}"
                output.write(f"DROP EVENT IF EXISTS {identifier};\n")
                _write_delimited_create(
                    output, _show_create(cursor, f"SHOW CREATE EVENT {identifier}")
                )

            output.write("\nSET FOREIGN_KEY_CHECKS=1;\n")
            db.commit()
        temporary.replace(destination)
        return DatabaseDump(database, str(destination), "success")
    except (OSError, pymysql.MySQLError, RuntimeError) as exc:
        temporary.unlink(missing_ok=True)
        return DatabaseDump(database, None, "error", str(exc))
    finally:
        if db is not None:
            db.close()


def dump_database(
    connection: RuntimeConnection,
    database: str,
    destination: Path,
    *,
    mysqldump_path: str,
) -> DatabaseDump:
    """Un proceso ``mysqldump``, con publicación atómica del archivo."""
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    environment = os.environ.copy()
    # MYSQL_PWD mantiene el secreto fuera de los argumentos del proceso.
    environment["MYSQL_PWD"] = connection.password
    command = [
        mysqldump_path,
        f"--host={connection.host}",
        f"--port={connection.port}",
        f"--user={connection.user}",
        "--single-transaction",
        "--routines",
        "--events",
        "--triggers",
        "--databases",
        database,
    ]
    try:
        with temporary.open("xb") as output:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
            )
        if completed.returncode:
            temporary.unlink(missing_ok=True)
            message = (completed.stderr or "mysqldump finalizo con error").strip()
            return DatabaseDump(database, None, "error", message)
        temporary.replace(destination)
        return DatabaseDump(database, str(destination), "success")
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        return DatabaseDump(database, None, "error", str(exc))


def pick_dump_runner(mysqldump_path: str = "mysqldump", dump_engine: str = "auto"):
    """Elige el motor de dump. ``auto`` usa mysqldump si existe."""
    has_mysqldump = shutil.which(mysqldump_path) is not None
    if dump_engine == "mysqldump" and not has_mysqldump:
        raise FileNotFoundError(
            f"No se encontro mysqldump ({mysqldump_path}). Use --dump-engine python "
            "o instale MySQL Client."
        )
    if dump_engine == "python" or (dump_engine == "auto" and not has_mysqldump):
        return dump_database_with_python
    return lambda connection, database, destination: dump_database(
        connection, database, destination, mysqldump_path=mysqldump_path
    )

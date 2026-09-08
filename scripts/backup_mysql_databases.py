"""Genera un dump consistente por cada base de datos MySQL accesible.

La contrasena nunca se incluye en la linea de comandos ni en los archivos de
salida. Se obtiene de la configuracion DPAPI del usuario que ejecuta el script.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql

from app.config.secure_credentials import (
    RuntimeConnection,
    default_config_dir,
    load_runtime_connection,
)


SYSTEM_DATABASES = frozenset({"information_schema", "mysql", "performance_schema", "sys"})


def default_backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", default_config_dir() / "backups")) / "mysql"


@dataclass(frozen=True)
class DatabaseDump:
    database: str
    file_path: str | None
    status: str
    message: str | None = None


def accessible_databases(connection: RuntimeConnection) -> list[str]:
    """Return non-system schemas visible to the configured MySQL user."""
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


def safe_database_filename(database: str) -> str:
    """Produce a portable, deterministic filename without changing the schema name."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", database).strip("._")
    return safe_name or "database"


def dump_database(
    connection: RuntimeConnection,
    database: str,
    destination: Path,
    *,
    mysqldump_path: str,
) -> DatabaseDump:
    """Run one mysqldump process and atomically publish its SQL file on success."""
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    environment = os.environ.copy()
    # MYSQL_PWD keeps the secret out of process arguments and command history.
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


def create_backup(
    connection: RuntimeConnection,
    backup_dir: Path,
    *,
    databases: list[str] | None = None,
    mysqldump_path: str = "mysqldump",
    now: datetime | None = None,
) -> tuple[Path, list[DatabaseDump]]:
    """Dump each requested schema into an independently restorable SQL file."""
    if shutil.which(mysqldump_path) is None:
        raise FileNotFoundError(
            f"No se encontro mysqldump ({mysqldump_path}). Instale MySQL Client o use --mysqldump."
        )

    target_databases = databases if databases is not None else accessible_databases(connection)
    if not target_databases:
        raise RuntimeError("No hay bases de datos de usuario accesibles para respaldar.")

    timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    run_dir = backup_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    results = [
        dump_database(
            connection,
            database,
            run_dir / f"{safe_database_filename(database)}.sql",
            mysqldump_path=mysqldump_path,
        )
        for database in target_databases
    ]
    manifest = {
        "created_at": (now or datetime.now().astimezone()).isoformat(),
        "databases": [asdict(result) for result in results],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_dir, results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera un archivo .sql separado por cada base MySQL accesible."
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=default_backup_dir(),
        help="Carpeta raiz de los dumps (por defecto: BACKUP_DIR/mysql).",
    )
    parser.add_argument(
        "--database",
        action="append",
        dest="databases",
        help="Base a respaldar. Repetir para evitar usar SHOW DATABASES.",
    )
    parser.add_argument(
        "--mysqldump",
        default="mysqldump",
        help="Ruta a mysqldump.exe o comando disponible en PATH.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        connection = load_runtime_connection()
        run_dir, results = create_backup(
            connection,
            args.backup_dir,
            databases=args.databases,
            mysqldump_path=args.mysqldump,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for result in results:
        if result.status == "success":
            print(f"OK {result.database}: {result.file_path}")
        else:
            print(f"ERROR {result.database}: {result.message}", file=sys.stderr)
    print(f"Manifiesto: {run_dir / 'manifest.json'}")
    return 0 if all(result.status == "success" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

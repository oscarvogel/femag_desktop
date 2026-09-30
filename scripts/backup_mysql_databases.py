"""Genera un dump consistente por cada base de datos MySQL accesible.

La contrasena nunca se incluye en la linea de comandos ni en los archivos de
salida. Se obtiene de la configuracion DPAPI del usuario que ejecuta el script.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
from app.services.mysql_dump import (
    DatabaseDump,
    accessible_databases,
    dump_database,
    dump_database_with_python,
    quote_identifier,
    safe_database_filename,
)

def default_backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", default_config_dir() / "backups")) / "mysql"

def create_backup(
    connection: RuntimeConnection,
    backup_dir: Path,
    *,
    databases: list[str] | None = None,
    mysqldump_path: str = "mysqldump",
    dump_engine: str = "auto",
    now: datetime | None = None,
) -> tuple[Path, list[DatabaseDump]]:
    """Dump each requested schema into an independently restorable SQL file."""
    has_mysqldump = shutil.which(mysqldump_path) is not None
    if dump_engine == "mysqldump" and not has_mysqldump:
        raise FileNotFoundError(
            f"No se encontro mysqldump ({mysqldump_path}). Use --dump-engine python o instale MySQL Client."
        )
    dump_runner = (
        dump_database_with_python
        if dump_engine == "python" or (dump_engine == "auto" and not has_mysqldump)
        else dump_database
    )

    target_databases = databases if databases is not None else accessible_databases(connection)
    if not target_databases:
        raise RuntimeError("No hay bases de datos de usuario accesibles para respaldar.")

    timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    run_dir = backup_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    results = [
        dump_runner(
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
        help="Ruta a mysqldump.exe o comando disponible en PATH cuando se usa el motor nativo.",
    )
    parser.add_argument(
        "--dump-engine",
        choices=("auto", "mysqldump", "python"),
        default="auto",
        help="auto usa mysqldump si existe y, si no, el exportador Python.",
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
            dump_engine=args.dump_engine,
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

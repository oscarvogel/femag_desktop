"""Comando administrativo de migración de columnas monetarias FLOAT -> DECIMAL.

**No se ejecuta al abrir FEMAG.** Son 30 ``ALTER TABLE ... MODIFY COLUMN`` sobre
importes; eso exige una operación explícita, con precheck y confirmación
humana. Este comando es ese gatillo.

Uso
---

Sólo informa, no modifica nada (por defecto)::

    py -m scripts.migrate_money_columns

Ejecuta la migración, y sólo después de un precheck verde::

    py -m scripts.migrate_money_columns --apply

Sobre otra base del mismo servidor (por ejemplo una copia local)::

    py -m scripts.migrate_money_columns --db femag_desktop_copia --apply

Garantías
---------

1. Usa **exactamente** la configuración efectiva de FEMAG (``.env`` / DPAPI),
   la misma que el auditor y que la aplicación, vía
   ``resolve_audit_database``. No hay un mecanismo paralelo de credenciales.
2. Corre el precheck antes de tocar nada y **aborta** si algún valor no entra en
   el DECIMAL destino o hay columnas fuera del alcance.
3. Es idempotente: si ya están migradas, informa ``ALREADY MIGRATED`` y no
   ejecuta ningún ``ALTER``.
4. Al terminar vuelve a leer ``information_schema`` y confirma cuántas
   columnas quedaron en el tipo exacto.
5. No recalcula nada: el ``ALTER`` es conversión de tipo, así que el importe
   histórico que ya estaba redondeado por la precisión simple sigue igual.
   La reparación de cada caso se hace después, uno por uno, con
   ``scripts.repair_monetary_integrity``.

Nota sobre transacciones
------------------------

En MySQL el DDL hace *implicit commit*: los 30 ``ALTER`` no se pueden envolver
en una transacción que los revierta en bloque. Si uno fallara a mitad de camino,
quedaría una parte migrada y otra no. Por eso la operación es idempotente y
vuelve a ejecutarse: terminarla es volver a correr el comando.
"""

from __future__ import annotations

import argparse
import json
import sys

from peewee import MySQLDatabase

from app.config.money_columns import (
    MONEY_COLUMNS,
    MoneyMigrationAbort,
    current_column_type,
    migrate_money_columns_to_decimal,
    needs_decimal_migration,
    precheck_money_columns,
    table_exists,
)
from app.services.monetary_audit_readonly import resolve_audit_database

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3
EXIT_NOTHING_TO_DO = 0

ALREADY_MIGRATED = "ALREADY MIGRATED"


# ---------------------------------------------------------------------------
# Apertura: MySQL pelado y escribible, sin preparación de esquema
# ---------------------------------------------------------------------------


def open_admin_database(target):
    """MySQL escribible sin ``ensure_runtime_schema``.

    Un comando administrativo no debe, al conectarse, disparar la preparación
    idempotente del esquema ni la siembra de medios de pago: sólo se quiere lo
    que el operador pidió. Por eso es un ``MySQLDatabase`` pelado y no el
    conector de la aplicación.
    """
    from app.config.database import resolve_mysql_host_ipv4

    if target.engine != "mysql":
        raise MoneyMigrationAbort(
            "La migración de columnas monetarias sólo aplica a MySQL. "
            f"La configuración efectiva apunta a {target.engine!r}."
        )
    database = MySQLDatabase(
        target.database,
        host=resolve_mysql_host_ipv4(target.host),
        port=target.port,
        user=target.user,
        password=target.password,
        charset="utf8mb4",
    )
    database.connect(reuse_if_open=True)
    return database


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


def render_plan(stats, *, database_label: str = "") -> str:
    lineas = ["MONEY COLUMN MIGRATION PLAN", "=" * 29, ""]
    if database_label:
        lineas += [f"Database: {database_label}", ""]
    lineas += [
        f"{'table':26} {'column':22} {'actual':12} {'destino':14} "
        f"{'filas':>7} {'nulos':>6} {'fuera':>6} {'cuantizar':>10}",
        "-" * 122,
    ]
    pendientes = 0
    cuantizados = 0
    fuera = 0
    for stat in stats:
        destino = stat.column.decimal_type
        if not stat.actual_type or not needs_decimal_migration(
            stat.actual_type, stat.column
        ):
            destino += " ok"
        elif stat.actual_type:
            pendientes += 1
        else:
            pendientes += 1
        fuera += stat.out_of_range
        cuantizados += stat.off_scale
        lineas.append(
            f"{stat.column.table:26} {stat.column.column:22} "
            f"{(stat.actual_type or '-'):12} {destino:14} "
            f"{stat.rows:>7} {stat.nulls:>6} {stat.out_of_range:>6} {stat.off_scale:>10}"
        )
    lineas.append("")
    lineas.append(f"Columnas registradas        : {len(MONEY_COLUMNS)}")
    lineas.append(f"Columnas a migrar           : {pendientes}")
    lineas.append(f"Valores fuera del destino   : {fuera}")
    lineas.append(
        f"Valores que se cuantizarán   : {cuantizados} "
        "(se redondean a 2 decimales; es el valor comercial correcto)"
    )
    lineas.append("")
    lineas.append(
        "El ALTER es conversión de tipo: NO recalcula históricos. Un importe ya\n"
        "redondeado por la precisión simple de FLOAT queda como está."
    )
    return "\n".join(lineas)


def verify_migrated(database) -> tuple[int, int]:
    """Vuelve a leer ``information_schema``. Devuelve (pendientes, exactas)."""
    pendientes = 0
    exactas = 0
    for columna in MONEY_COLUMNS:
        if not table_exists(database, columna.table):
            continue
        actual = current_column_type(database, columna.table, columna.column)
        if actual is None:
            continue
        if needs_decimal_migration(actual, columna):
            pendientes += 1
        else:
            exactas += 1
    return pendientes, exactas


def verify_payload(database) -> dict:
    """Payload JSON de verificación, para orquestadores."""
    pendientes, exactas = verify_migrated(database)
    return {
        "columns_registered": len(MONEY_COLUMNS),
        "columns_to_migrate": pendientes,
        "columns_exact_decimal": exactas,
        "migrated": pendientes == 0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.migrate_money_columns",
        description=(
            "Migración explícita de columnas monetarias FLOAT a DECIMAL(18,2). "
            "Sin --apply sólo informa y no modifica nada."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ejecutar los ALTER. Sin este flag el comando es sólo un precheck.",
    )
    parser.add_argument(
        "--db", metavar="NOMBRE", help="Migrar otra base del mismo servidor."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida JSON para orquestadores (no imprime el plan).",
    )
    return parser


def run_migration(argv=None, *, open_database=None, quiet=False) -> int:
    """Ejecuta el comando. ``open_database`` se inyecta para poder testearlo."""
    args = build_parser().parse_args(argv)

    def _echo(linea=""):
        if not quiet:
            print(linea)

    try:
        target = resolve_audit_database(database_name=args.db)
    except Exception as exc:
        mensaje = (
            f"no se pudo resolver la conexión de FEMAG: {type(exc).__name__}: {exc}"
        )
        if args.json:
            print(json.dumps({"ok": False, "error": mensaje}, ensure_ascii=False))
        else:
            print(f"ERROR: {mensaje}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    etiqueta = f"{target.host}:{target.port}/{target.database} (user {target.user})"

    if open_database is None:
        open_database = open_admin_database

    try:
        database = open_database(target)
    except MoneyMigrationAbort as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"ABORTED: {exc}", file=sys.stderr)
        return EXIT_ABORTED
    except Exception as exc:
        mensaje = f"no se pudo abrir la conexión: {type(exc).__name__}: {exc}"
        if args.json:
            print(json.dumps({"ok": False, "error": mensaje}, ensure_ascii=False))
        else:
            print(f"ERROR: {mensaje}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    try:
        try:
            stats = precheck_money_columns(database)
        except MoneyMigrationAbort as exc:
            if args.json:
                print(
                    json.dumps(
                        {"ok": False, "aborted": True, "error": str(exc)},
                        ensure_ascii=False,
                    )
                )
            else:
                print(f"ABORTED: {exc}", file=sys.stderr)
                print("No se ejecutó ningún ALTER.", file=sys.stderr)
            return EXIT_ABORTED

        pendientes, _exactas = verify_migrated(database)

        if not args.apply:
            payload = verify_payload(database)
            if args.json:
                print(json.dumps({"ok": True, "applied": False, **payload}, ensure_ascii=False))
                return EXIT_OK
            _echo(render_plan(stats, database_label=etiqueta))
            _echo()
            _echo(f"Pendientes de migrar: {pendientes}")
            _echo(f"Ya en DECIMAL exacto  : {_exactas}")
            _echo()
            _echo("PRECHECK ONLY: no se modificó nada.")
            _echo("Para migrar, revisá el plan y volvé a ejecutar con --apply.")
            return EXIT_OK

        if pendientes == 0:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "applied": False,
                            "already_migrated": True,
                            **verify_payload(database),
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                _echo(ALREADY_MIGRATED)
                _echo("No se ejecutó ningún ALTER.")
            return EXIT_NOTHING_TO_DO

        _echo(f"Ejecutando {pendientes} ALTER TABLE ... MODIFY COLUMN ...")
        alteradas = migrate_money_columns_to_decimal(database)
        for tabla, columna, cambio in alteradas:
            _echo(f"  {tabla}.{columna}: {cambio}")

        pendientes_final, exactas_final = verify_migrated(database)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": pendientes_final == 0,
                        "applied": True,
                        "altered": len(alteradas),
                        "columns_to_migrate": pendientes_final,
                        "columns_exact_decimal": exactas_final,
                    },
                    ensure_ascii=False,
                )
            )
            return EXIT_OK if pendientes_final == 0 else EXIT_ABORTED

        _echo()
        _echo(f"Columnas alteradas: {len(alteradas)}")
        _echo()
        _echo("VERIFY (information_schema)")
        _echo(f"  Columnas a migrar      : {pendientes_final}")
        _echo(f"  DECIMAL exacto         : {exactas_final}")
        if pendientes_final:
            _echo(
                "  Quedan columnas pendientes: volvé a ejecutar el comando para "
                "terminar."
            )
            return EXIT_ABORTED
        _echo()
        _echo("MIGRATED")
        _echo(
            "Los históricos NO se alteraron. La reparación de cada caso se hace "
            "con\npy -m scripts.repair_monetary_integrity --budget-number <n> "
            "--apply, uno por uno."
        )
        return EXIT_OK
    finally:
        try:
            database.close()
        except Exception:  # pragma: no cover - cierre defensivo
            pass


def main(argv=None) -> int:
    return run_migration(argv)


if __name__ == "__main__":
    raise SystemExit(main())

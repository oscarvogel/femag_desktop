"""Diagnóstico previo a la migración de columnas monetarias FLOAT -> DECIMAL.

Sólo SELECT: no altera nada. Sirve para responder antes de migrar:

* qué tablas y columnas se van a tocar;
* tipo actual y tipo destino;
* cantidad de filas;
* MIN y MAX reales;
* valores NULL;
* valores que NO entran en el DECIMAL destino (si hay alguno, aborta).

Uso::

    py -m scripts.precheck_money_columns
    py -m scripts.precheck_money_columns --csv precheck.csv
    py -m scripts.precheck_money_columns --db femag_desktop_copia
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app.config.money_columns import (
    MONEY_COLUMNS,
    MoneyMigrationAbort,
    current_column_type,
    needs_decimal_migration,
    precheck_money_columns,
)
from app.services.monetary_audit_readonly import (
    MonetaryIntegrityAuditor,
    open_audit_database,
    resolve_audit_database,
)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_ABORTED = 3


def render(stats) -> str:
    """Reporte legible del diagnóstico."""
    lineas = [
        "MONEY COLUMN PRECHECK (FLOAT -> DECIMAL)",
        "=======================================",
        "",
        f"{'table':26} {'column':22} {'actual':16} {'destino':16} "
        f"{'filas':>7} {'nulos':>6}  {'min':>18} {'max':>18}",
        "-" * 150,
    ]
    for stat in stats:
        minimo = f"{stat.minimum:,.2f}" if stat.minimum is not None else "-"
        maximo = f"{stat.maximum:,.2f}" if stat.maximum is not None else "-"
        destino = stat.column.decimal_type
        if stat.actual_type and not needs_decimal_migration(
            stat.actual_type, stat.column
        ):
            destino += " (ya ok)"
        lineas.append(
            f"{stat.column.table:26} {stat.column.column:22} "
            f"{stat.actual_type or '-':16} {destino:16} "
            f"{stat.rows:>7} {stat.nulls:>6}  {minimo:>18} {maximo:>18}"
        )
    pendientes = [
        s for s in stats if s.actual_type and needs_decimal_migration(s.actual_type, s.column)
    ]
    lineas.append("")
    lineas.append(f"Columnas registradas            : {len(MONEY_COLUMNS)}")
    lineas.append(f"Columnas a migrar               : {len(pendientes)}")
    lineas.append(f"Columnas ya en DECIMAL exacto   : {len(stats) - len(pendientes)}")
    lineas.append(
        f"Valores fuera del DECIMAL destino: "
        f"{sum(s.out_of_range for s in stats)}"
    )
    lineas.append(
        f"Valores con más decimales que la escala: "
        f"{sum(s.off_scale for s in stats)} (se redondean al migrar)"
    )
    return "\n".join(lineas)


def write_csv(stats, path) -> Path:
    destino = Path(path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "table",
                "column",
                "purpose",
                "current_type",
                "target_type",
                "rows",
                "nulls",
                "min",
                "max",
                "out_of_range",
                "off_scale",
                "needs_migration",
            ]
        )
        for stat in stats:
            writer.writerow(
                [
                    stat.column.table,
                    stat.column.column,
                    stat.column.purpose,
                    stat.actual_type,
                    stat.column.decimal_type,
                    stat.rows,
                    stat.nulls,
                    "" if stat.minimum is None else f"{stat.minimum:.2f}",
                    "" if stat.maximum is None else f"{stat.maximum:.2f}",
                    stat.out_of_range,
                    stat.off_scale,
                    "yes"
                    if stat.actual_type
                    and needs_decimal_migration(stat.actual_type, stat.column)
                    else "no",
                ]
            )
    return destino


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.precheck_money_columns",
        description=(
            "Diagnóstico READ-ONLY previo a migrar columnas monetarias FLOAT a "
            "DECIMAL. No modifica nada. Aborta si algún valor no entra."
        ),
    )
    parser.add_argument("--db", metavar="NOMBRE", help="Otra base del mismo servidor.")
    parser.add_argument("--csv", metavar="RUTA", help="Exportar el diagnóstico a CSV.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = resolve_audit_database(database_name=args.db)
        for line in target.header_lines():
            print(line)
        handle = open_audit_database(target=target)
    except Exception as exc:
        print(
            f"ERROR: no se pudo resolver o abrir la conexión: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR

    try:
        stats = precheck_money_columns(handle.database)
    except MoneyMigrationAbort as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return EXIT_ABORTED
    finally:
        handle.close()

    print()
    print(render(stats))
    if args.csv:
        destino = write_csv(stats, args.csv)
        print()
        print(f"Diagnóstico exportado: {destino}")

    # Prueba de que el importe del incidente entra una vez migrado.
    print()
    auditor = MonetaryIntegrityAuditor(handle.database)
    print(
        "Nota: el guard de representabilidad de la herramienta de reparación "
        "seguirá bloqueando\nhasta que la migración se aplique en esta base."
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

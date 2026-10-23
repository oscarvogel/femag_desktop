"""Importa la lista de precios (y completa el teléfono) desde un Excel exportado por la app.

Es el mismo servicio que usa la pantalla de Clientes, para correrlo desde la terminal
(por ejemplo, en el despliegue o cuando hay que aplicar el archivo sin tocar la pantalla).

    python scripts/import_client_price_lists.py "C:\\...\\clientes_20261021.xlsx"
    python scripts/import_client_price_lists.py "C:\\...\\clientes_20261021.xlsx" --aplicar

Sin ``--aplicar`` solo muestra la vista previa: **no escribe nada**.

Códigos de salida:

- ``0``: todo bien (aplicado, o solo vista previa).
- ``1``: error (archivo inválido, no se pudo aplicar).
- ``2``: se aplicó, pero quedan conflictos o filas sin aplicar para revisar.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.services.client_price_list_import_service import (
    ClientPriceListImporter,
    ImportPriceListError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa la lista de precios y el teléfono desde un Excel de clientes."
    )
    parser.add_argument("archivo", help="Ruta del .xlsx con las columnas CUIT y Lista.")
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Aplica los cambios. Sin esta opción solo muestra la vista previa.",
    )
    parser.add_argument(
        "--usuario",
        default="importacion",
        help="Usuario que queda en la auditoría de los cambios.",
    )
    parser.add_argument(
        "--directorio-respaldo",
        help="Carpeta donde dejar el respaldo. Por defecto, la del archivo importado.",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    archivo = Path(args.archivo)
    if not archivo.is_file():
        print(f"El archivo no existe: {archivo}", file=sys.stderr)
        return 1

    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    try:
        importador = ClientPriceListImporter(current_user=args.usuario)
        try:
            vista = importador.construir_vista_previa(archivo)
        except ImportPriceListError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        resultado = None
        if args.aplicar:
            resultado = importador.aplicar(
                vista,
                directorio_respaldo=args.directorio_respaldo,
            )
    finally:
        if not database.is_closed():
            database.close()

    if args.json:
        print(
            json.dumps(
                {
                    "archivo": str(archivo),
                    "resumen": vista.resumen(),
                    "conflictos": [
                        {
                            "tipo": conflicto.tipo,
                            "detalle": conflicto.detalle,
                            "cuit": conflicto.cuit,
                            "filas": list(conflicto.filas),
                        }
                        for conflicto in vista.conflictos
                    ],
                    "no_encontrados": [
                        {
                            "fila": fila.fila,
                            "nombre": fila.nombre,
                            "cuit": fila.cuit,
                            "motivo": fila.motivo,
                        }
                        for fila in vista.no_encontrados
                    ],
                    "invalidos": [
                        {"fila": fila.fila, "nombre": fila.nombre, "motivo": fila.motivo}
                        for fila in vista.invalidos
                    ],
                    "aplicado": {
                        "cambios_lista": resultado.cambios_lista if resultado else 0,
                        "cambios_telefono": resultado.cambios_telefono if resultado else 0,
                        "respaldo": resultado.respaldo if resultado else "",
                        "errores": list(resultado.errores) if resultado else [],
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        resumen = vista.resumen()
        print(f"Archivo: {archivo}")
        print(f"Filas leídas: {resumen['filas']}")
        print(
            f"Lista a cambiar: {resumen['cambios_lista']} · "
            f"Teléfonos a completar: {resumen['cambios_telefono']} · "
            f"Sin cambio: {resumen['sin_cambio']}"
        )
        print(
            f"Conflictos: {resumen['conflictos']} · "
            f"No encontrados: {resumen['no_encontrados']} · "
            f"Inválidos: {resumen['invalidos']}"
        )
        print(f"Diferencias informadas (no se aplican): {resumen['diferencias']}")
        print(f"Clientes que el archivo no menciona (no se tocan): {resumen['faltantes']}")

        if vista.conflictos:
            print()
            print("Conflictos (no se aplican):")
            for conflicto in vista.conflictos:
                print(f"   [{conflicto.tipo}] {conflicto.detalle}")
                if conflicto.filas:
                    print(f"      filas del Excel: {', '.join(str(f) for f in conflicto.filas)}")
        if vista.no_encontrados:
            print()
            print("Filas sin aplicar:")
            for fila in vista.no_encontrados:
                print(f"   fila {fila.fila} · {fila.nombre} · {fila.motivo}")
        if vista.invalidos:
            print()
            print("Filas inválidas:")
            for fila in vista.invalidos:
                print(f"   fila {fila.fila} · {fila.nombre} · {fila.motivo}")

        if resultado is not None:
            print()
            if resultado.errores:
                print("No se pudo aplicar:")
                for error in resultado.errores:
                    print(f"   - {error}")
            else:
                print(
                    f"Aplicado: {resultado.cambios_lista} listas y "
                    f"{resultado.cambios_telefono} teléfonos."
                )
                print(f"Respaldo: {resultado.respaldo}")

    if resultado is not None and resultado.errores:
        return 1
    if vista.conflictos or vista.no_encontrados or vista.invalidos:
        return 2 if resultado is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

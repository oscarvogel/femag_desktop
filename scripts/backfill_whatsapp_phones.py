"""Copia al campo de WhatsApp los celulares que ya estan cargados (#923).

Es el backfill de la migracion: los contactos que ya tienen un celular en el
telefono general se les copia ese numero al campo de WhatsApp. Solo se copia
lo que el clasificador da como **celular**: un numero dudoso se deja vacio a
proposito, para que lo confirme el operador.

Sin ``--aplicar`` solo muestra la vista previa: **no escribe nada**.

    python scripts/backfill_whatsapp_phones.py
    python scripts/backfill_whatsapp_phones.py --aplicar --usuario admin

Codigos de salida:

- ``0``: todo bien (aplicado, o solo vista previa).
- ``1``: error (no se pudo aplicar).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.services.whatsapp_contact_service import (
    ESTADOS_DE_TELEFONO,
    BackfillInforme,
    WhatsAppContactService,
)

#: Cuantos omitidos se listan en la salida humana. Con la base real son 219:
# imprimirlos todos en la consola no sirve para nada.
MAXIMO_DE_OMITIDOS = 20


def _desarmar_motivo(motivo: str) -> tuple[str, str]:
    """Separa "posible: ..." en el estado y la explicacion."""
    estado, _, detalle = motivo.partition(":")
    return estado.strip(), detalle.strip()


def _por_estado(informe: BackfillInforme) -> dict[str, dict[str, int]]:
    """Cuantos contactos hay de cada tipo y estado, contando los copiados.

    Los copiados son los que el clasificador dio como ``celular``: van en su
    propio grupo, no entre los omitidos.
    """
    por_estado = {
        tipo: dict(estados) for tipo, estados in informe.omitidos_por_estado.items()
    }
    por_estado.setdefault("cliente", {estado: 0 for estado in ESTADOS_DE_TELEFONO})
    por_estado.setdefault("vendedor", {estado: 0 for estado in ESTADOS_DE_TELEFONO})
    por_estado["cliente"]["celular"] += informe.copiados_clientes
    por_estado["vendedor"]["celular"] += informe.copiados_vendedores
    return por_estado


def _considerados(informe: BackfillInforme) -> dict[str, int]:
    """Cuantos contactos se miraron, por tipo."""
    return {
        "cliente": informe.copiados_clientes
        + sum(informe.omitidos_por_estado.get("cliente", {}).values()),
        "vendedor": informe.copiados_vendedores
        + sum(informe.omitidos_por_estado.get("vendedor", {}).values()),
    }


def _informe_json(informe: BackfillInforme, *, aplicar: bool) -> dict:
    """El informe completo, para consumirlo con otra herramienta."""
    return {
        "modo": "aplicado" if aplicar else "vista_previa",
        "aplicado": aplicar,
        "copiados_clientes": informe.copiados_clientes,
        "copiados_vendedores": informe.copiados_vendedores,
        "copiados_clientes_inactivos": informe.copiados_clientes_inactivos,
        "considerados": _considerados(informe),
        "por_estado": _por_estado(informe),
        "omitidos": [
            {
                "tipo": tipo,
                "nombre": nombre,
                "estado": _desarmar_motivo(motivo)[0],
                "motivo": _desarmar_motivo(motivo)[1],
            }
            for tipo, nombre, motivo in informe.omitidos
        ],
    }


def _resumen_humano(informe: BackfillInforme, *, aplicar: bool) -> str:
    """El resumen para la consola: cuantos se copian y cuantos quedan sin destino."""
    considerados = _considerados(informe)
    por_estado = _por_estado(informe)
    lineas = []
    if aplicar:
        lineas.append("Backfill de los WhatsApp (#923) - APLICADO")
        lineas.append("")
        lineas.append(
            f"Se copiaron {informe.copiados_clientes} clientes y "
            f"{informe.copiados_vendedores} vendedores."
        )
    else:
        lineas.append("Backfill de los WhatsApp (#923) - VISTA PREVIA")
        lineas.append("No se escribe nada: esto es solo lo que se copiaria.")
        lineas.append("")
        lineas.append(
            f"Se copiarian {informe.copiados_clientes} clientes y "
            f"{informe.copiados_vendedores} vendedores."
        )
    if informe.copiados_clientes_inactivos:
        cantidad = informe.copiados_clientes_inactivos
        palabra = "cliente inactivo" if cantidad == 1 else "clientes inactivos"
        lineas.append(
            f"De los copiados, {cantidad} {palabra} "
            "(se copian igual: es un hecho sobre el telefono)."
        )
    lineas.append("")

    for tipo, plural in (("cliente", "Clientes"), ("vendedor", "Vendedores")):
        lineas.append(
            f"{plural} sin WhatsApp cargado: {considerados.get(tipo, 0)}"
        )
        for estado in ESTADOS_DE_TELEFONO:
            cantidad = por_estado.get(tipo, {}).get(estado, 0)
            nota = " (se copian)" if estado == "celular" else ""
            lineas.append(f"   {estado}: {cantidad}{nota}")
        lineas.append("")

    if informe.omitidos:
        lineas.append(
            f"Quedan sin destino {len(informe.omitidos)} contactos "
            "(a confirmar por el operador):"
        )
        for tipo, nombre, motivo in informe.omitidos[:MAXIMO_DE_OMITIDOS]:
            lineas.append(f"   {tipo} | {nombre} | {motivo}")
        if len(informe.omitidos) > MAXIMO_DE_OMITIDOS:
            lineas.append(f"   ... y {len(informe.omitidos) - MAXIMO_DE_OMITIDOS} mas.")
        lineas.append("")
        lineas.append("El detalle completo esta en la salida con --json.")
    else:
        lineas.append("No queda ningun contacto sin destino.")
    return "\n".join(lineas)


def main(argv: list[str] | None = None, database=None) -> int:
    parser = argparse.ArgumentParser(
        description="Copia al campo de WhatsApp los celulares que ya estan cargados."
    )
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Aplica los cambios. Sin esta opcion solo muestra la vista previa.",
    )
    parser.add_argument(
        "--usuario",
        default="backfill",
        help="Usuario que queda en la auditoria de los cambios.",
    )
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    # La base se abre y se cierra aca salvo que la pase el que llama (los
    # tests): si la abrio este script, la cierra este script.
    propia_base = database is None
    if database is None:
        database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    try:
        # Es lo que agrega la columna ``whatsapp_phone`` cuando falta. Es
        # idempotente: si ya esta, no hace nada.
        ensure_runtime_schema(database)
        servicio = WhatsAppContactService(args.usuario)
        informe = servicio.backfill(aplicar=args.aplicar)
    except Exception as exc:  # noqa: BLE001 - el error se le avisa al operador
        print(f"No se pudo hacer el backfill: {exc}", file=sys.stderr)
        return 1
    finally:
        if propia_base and not database.is_closed():
            database.close()

    if args.json:
        print(
            json.dumps(
                _informe_json(informe, aplicar=args.aplicar),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_resumen_humano(informe, aplicar=args.aplicar))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

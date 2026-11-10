"""Prellenado de la ficha de orden desde una propuesta de IA (#913).

La IA no escribe: esta capa toma la propuesta validada y arma los grupos de
pallets que la plantilla muestra prellenados. El operador revisa y el guardado
sigue usando ``webapp.order_service`` / ``webapp.projected_order_service``.

Reglas de reparto:
- Un solo lote detectado: se aplica al primer grupo de la linea.
- Varios lotes con cantidad de pallets conocida y suma exacta: se reparten los
  slots en orden y se arma un grupo por lote.
- Varios lotes sin reparto seguro: se aplica el primero y se avisa.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.order_capture_ai_service import CaptureLot, CaptureProposal
from webapp.load_groups import LoadGroup, LoadLine


def _slot_sort_key(slot: str):
    try:
        return (0, int(slot))
    except (TypeError, ValueError):
        return (1, str(slot))


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _merge_lot(existing: LoadGroup, lot: CaptureLot) -> LoadGroup:
    return replace(
        existing,
        lote=lot.lote or existing.lote,
        fecha_elaboracion=(
            lot.fecha_elaboracion.isoformat()
            if lot.fecha_elaboracion
            else existing.fecha_elaboracion
        ),
        fecha_envasado=(
            lot.fecha_envasado.isoformat()
            if lot.fecha_envasado
            else existing.fecha_envasado
        ),
    )


def _differs(existing: LoadGroup, lot: CaptureLot) -> bool:
    return bool(
        (existing.lote and lot.lote and existing.lote != lot.lote)
        or (
            existing.fecha_elaboracion
            and lot.fecha_elaboracion
            and existing.fecha_elaboracion != lot.fecha_elaboracion.isoformat()
        )
        or (
            existing.fecha_envasado
            and lot.fecha_envasado
            and existing.fecha_envasado != lot.fecha_envasado.isoformat()
        )
    )


def _groups_from_lots(
    line: LoadLine,
    lots: list[CaptureLot],
) -> tuple[tuple[LoadGroup, ...], list[str]]:
    warnings: list[str] = []
    current = list(line.groups) or [LoadGroup(index=0)]
    first = current[0]

    if len(lots) == 1:
        lot = lots[0]
        if _differs(first, lot):
            warnings.append(
                "Se reemplazó el lote/fecha que ya tenía la línea por el detectado en la imagen."
            )
        return tuple([_merge_lot(first, lot), *current[1:]]), warnings

    slots = sorted(line.slots, key=_slot_sort_key)
    counts = [lot.pallets for lot in lots]
    if (
        slots
        and all(count is not None and count > 0 for count in counts)
        and sum(counts) == len(slots)
    ):
        groups: list[LoadGroup] = []
        cursor = 0
        for index, lot in enumerate(lots):
            count = int(lot.pallets or 0)
            group_slots = tuple(slots[cursor : cursor + count])
            cursor += count
            groups.append(
                LoadGroup(
                    index=index,
                    lote=lot.lote,
                    fecha_elaboracion=_iso(lot.fecha_elaboracion),
                    fecha_envasado=_iso(lot.fecha_envasado),
                    slots=group_slots,
                )
            )
        return tuple(groups), warnings

    lot = lots[0]
    if _differs(first, lot):
        warnings.append(
            "Se reemplazó el lote/fecha que ya tenía la línea por el detectado en la imagen."
        )
    warnings.append(
        f"Se detectaron {len(lots)} lotes para esta línea, pero no se pudo "
        "repartir los pallets con seguridad. Se cargó el primero; revisá el resto a mano."
    )
    return tuple([_merge_lot(first, lot), *current[1:]]), warnings


def _review_entry(proposal_line) -> dict:
    return {
        "status": "sin_datos",
        "confidence": proposal_line.confidence,
        "match_status": proposal_line.match_status,
        "detected": {
            "producto": proposal_line.product_text,
            "destino": proposal_line.destination_text,
            "lotes": [
                {
                    "lote": lot.lote,
                    "fecha_elaboracion": _iso(lot.fecha_elaboracion),
                    "fecha_envasado": _iso(lot.fecha_envasado),
                    "pallets": lot.pallets,
                    "confianza": lot.confidence,
                }
                for lot in proposal_line.lots
            ],
        },
        "warnings": list(proposal_line.warnings),
        "applied": False,
    }


def apply_capture_to_load_lines(
    load_lines: list[LoadLine],
    proposal: CaptureProposal,
) -> tuple[list[LoadLine], dict[str, dict]]:
    """Devuelve las lineas prellenadas y el detalle para la pantalla."""

    proposed = {
        line.line_key: line
        for line in proposal.lines
        if line.line_key is not None
    }
    result: list[LoadLine] = []
    review: dict[str, dict] = {}

    for line in load_lines:
        proposal_line = proposed.get(line.key)
        if proposal_line is None:
            review[line.key] = {
                "status": "sin_datos",
                "confidence": 0.0,
                "match_status": "",
                "detected": None,
                "warnings": [],
                "applied": False,
            }
            result.append(line)
            continue

        entry = _review_entry(proposal_line)
        if proposal_line.match_status == "ambiguous":
            entry["status"] = "ambiguo"
            entry["warnings"].append(
                "La IA no pudo distinguir a qué línea pertenece. Revisá el cliente/destino."
            )
        elif proposal_line.match_status == "unmatched":
            entry["status"] = "sin_coincidencia"
            entry["warnings"].append(
                "La IA detectó una línea que no coincide con esta orden."
            )
        else:
            lots = [
                lot
                for lot in proposal_line.lots
                if lot.lote or lot.fecha_elaboracion or lot.fecha_envasado
            ]
            if not lots:
                entry["warnings"].append(
                    "La IA no detectó lote ni fechas para esta línea."
                )
            else:
                groups, warnings = _groups_from_lots(line, lots)
                entry["warnings"].extend(warnings)
                line = replace(line, groups=groups)
                entry["status"] = "aplicado"
                entry["applied"] = True

        review[line.key] = entry
        result.append(line)

    return result, review


def summarize_capture(proposal: CaptureProposal, review: dict[str, dict]) -> dict:
    applied = sum(1 for entry in review.values() if entry.get("applied"))
    review_count = len(
        [
            line
            for line in proposal.lines
            if line.match_status in {"ambiguous", "unmatched"}
        ]
    ) + sum(
        1
        for entry in review.values()
        if entry.get("status") in {"ambiguo", "sin_coincidencia"}
    )
    return {
        "applied": applied,
        "review": review_count,
        "detected": len(proposal.lines),
    }

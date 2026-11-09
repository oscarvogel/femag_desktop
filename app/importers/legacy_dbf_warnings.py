from __future__ import annotations

from collections import Counter
from typing import Any


#: Clasificación operativa de las advertencias del importador legacy.
#:
#: - ``expected``: conflicto propio del origen DBF; el importador ya tomó la
#:   decisión segura y no requiere acción.
#: - ``review``: el dato quedó incompleto o ambiguo; una persona debe revisarlo.
#: - ``bug``: el importador no pudo resolver algo que debería poder resolver.
WARNING_CATALOG: dict[str, dict[str, str]] = {
    "client_cuit_shared_by_two_rows": {
        "classification": "expected",
        "description": "El legacy repite el mismo CUIT en dos filas; el importador absorbe una.",
        "action": "Ninguna. Revisar sólo si el cliente es distinto.",
    },
    "client_cuit_taken_by_another_row": {
        "classification": "expected",
        "description": "El legacy asigna un CUIT que ya pertenece a otro cliente.",
        "action": "Ninguna. El cliente conserva su CUIT original.",
    },
    "carrier_code_collision": {
        "classification": "review",
        "description": "El código del chofer coincide con otro transportista y la identidad no coincide.",
        "action": "Asignar el transportista correcto desde Maestros.",
    },
    "carrier_not_found": {
        "classification": "review",
        "description": "No hay un transportista seguro para el chofer.",
        "action": "Asignar el transportista desde Maestros.",
    },
    "carrier_cuit_ambiguous": {
        "classification": "review",
        "description": "Más de un transportista comparte el CUIT del chofer.",
        "action": "Definir cuál corresponde y asignarlo manualmente.",
    },
    "truck_trailer_conflict": {
        "classification": "expected",
        "description": "El camión ya tenía otro acoplado; se conservó el valor del operador.",
        "action": "Revisar sólo si el acoplado cambió.",
    },
    "truck_carrier_conflict": {
        "classification": "expected",
        "description": "El camión ya pertenecía a otro transportista; se conservó el valor del operador.",
        "action": "Revisar sólo si el camión cambió de transportista.",
    },
    "habitual_truck_missing": {
        "classification": "expected",
        "description": "El chofer no trae patente habitual en el DBF.",
        "action": "Completar el camión habitual cuando se asigne.",
    },
}

ERROR_CLASSIFICATION = {
    "classification": "review",
    "description": "La fila no entró por un dato obligatorio faltante o un choque de clave.",
    "action": "Revisar la fila de origen y corregirla.",
}


def classify_warning(code: str | None) -> dict[str, str]:
    info = WARNING_CATALOG.get(code or "")
    if info is not None:
        return info
    return {
        "classification": "review",
        "description": "Advertencia sin clasificar.",
        "action": "Revisar el detalle de la importación.",
    }


def summarize_import_warnings(
    summary: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Agrupa las advertencias por código y separa las que requieren revisión."""
    by_code: Counter[str] = Counter()
    by_classification = {"expected": 0, "review": 0, "bug": 0}
    manual_review: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for entity, values in summary.items():
        if not isinstance(values, dict):
            continue
        for warning in values.get("warnings", []) or []:
            code = str(warning.get("code") or "sin_codigo")
            info = classify_warning(code)
            classification = info["classification"]
            by_code[code] += 1
            by_classification[classification] += 1
            if classification != "expected":
                manual_review.append(
                    {
                        "entity": entity,
                        "code": code,
                        "source_id": warning.get("source_id"),
                        "action": info["action"],
                    }
                )
        for error in values.get("errors", []) or []:
            message = error.get("message") if isinstance(error, dict) else str(error)
            source_id = error.get("source_id") if isinstance(error, dict) else None
            errors.append({"entity": entity, "message": message, "source_id": source_id})
            manual_review.append(
                {
                    "entity": entity,
                    "code": "error",
                    "source_id": source_id,
                    "action": ERROR_CLASSIFICATION["action"],
                }
            )

    return {
        "total_warnings": sum(by_code.values()),
        "total_errors": len(errors),
        "by_code": dict(sorted(by_code.items())),
        "by_classification": by_classification,
        "manual_review": manual_review,
        "errors": errors,
    }

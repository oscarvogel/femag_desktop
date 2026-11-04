"""Edicion auditada de lote y fechas por contenido de una orden de carga (#864)."""

from __future__ import annotations

from datetime import date, datetime

from app.config.database import database_proxy
from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncEntityMap
from app.services.audit_service import AuditService
from app.services.sync_service import SyncService

MAX_LOTE_LENGTH = 255

PALLET_CONTENT = "pallet_content"
LOOSE_CONTENT = "loose_content"
LINE = "line"

TRACEABILITY_FIELDS = ("lote", "fecha_elaboracion", "fecha_envasado")


class LoadOrderTraceabilityError(ValueError):
    pass


class LoadOrderTraceabilityService:
    """Actualiza lote/fechas sin tocar cantidades, precios, stock ni estados."""

    def __init__(
        self,
        current_user: str,
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def update_lote_fecha(
        self,
        order: LoadOrder,
        items: list[dict] | None,
        *,
        reason: str | None = None,
    ) -> int:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise LoadOrderTraceabilityError(
                "No se puede editar la trazabilidad de una orden anulada."
            )

        normalized_reason = (reason or "").strip() or None
        if order.status == LoadOrder.STATUS_CLOSED and normalized_reason is None:
            raise LoadOrderTraceabilityError(
                "En una orden cerrada debe indicar el motivo del cambio."
            )

        normalized_items = self._normalize_items(order, items)
        if not normalized_items:
            raise LoadOrderTraceabilityError("No hay contenidos para actualizar.")

        changed = 0
        with database_proxy.atomic():
            for item in normalized_items:
                changed += self._apply_item(item, order, normalized_reason)
            if changed:
                entity = SyncService.ensure_entity_uid(
                    SyncEntityMap.ENTITY_ORDER, order.id
                )
                SyncService.bump_entity_version(entity)
        return changed

    def _normalize_items(self, order: LoadOrder, items: list[dict] | None) -> list[dict]:
        normalized: list[dict] = []
        for raw in items or []:
            if not isinstance(raw, dict):
                raise LoadOrderTraceabilityError(
                    "Cada contenido a actualizar debe ser un detalle valido."
                )
            kind = str(raw.get("kind") or "").strip()
            if kind not in {PALLET_CONTENT, LOOSE_CONTENT, LINE}:
                raise LoadOrderTraceabilityError(
                    f"Tipo de contenido no soportado: {kind or '(vacio)'}."
                )
            item_id = raw.get("id")
            if item_id is None:
                raise LoadOrderTraceabilityError("Falta el identificador del contenido.")
            try:
                item_id = int(item_id)
            except (TypeError, ValueError) as exc:
                raise LoadOrderTraceabilityError(
                    "El identificador del contenido no es valido."
                ) from exc

            target = self._resolve_target(order, kind, item_id)
            lote = (raw.get("lote") or "").strip() or None
            if lote and len(lote) > MAX_LOTE_LENGTH:
                raise LoadOrderTraceabilityError(
                    f"El lote supera los {MAX_LOTE_LENGTH} caracteres."
                )
            normalized.append(
                {
                    "kind": kind,
                    "target": target,
                    "lote": lote,
                    "fecha_elaboracion": self._parse_date(
                        raw.get("fecha_elaboracion"), "fecha de elaboracion"
                    ),
                    "fecha_envasado": self._parse_date(
                        raw.get("fecha_envasado"), "fecha de envasado"
                    ),
                }
            )
        return normalized

    @staticmethod
    def _resolve_target(order: LoadOrder, kind: str, item_id: int):
        if kind == PALLET_CONTENT:
            allocation = LoadOrderPalletAllocation.get_or_none(
                LoadOrderPalletAllocation.id == item_id
            )
            if allocation is None or allocation.pallet.order_id != order.id:
                raise LoadOrderTraceabilityError(
                    "El contenido del pallet no pertenece a la orden."
                )
            return allocation
        if kind == LOOSE_CONTENT:
            allocation = LoadOrderLooseAllocation.get_or_none(
                LoadOrderLooseAllocation.id == item_id
            )
            if allocation is None or allocation.order_id != order.id:
                raise LoadOrderTraceabilityError(
                    "La mercaderia suelta no pertenece a la orden."
                )
            return allocation
        line = LoadOrderProduct.get_or_none(LoadOrderProduct.id == item_id)
        if line is None or line.order_id != order.id:
            raise LoadOrderTraceabilityError("El renglon no pertenece a la orden.")
        return line

    @staticmethod
    def _parse_date(value, label: str) -> date | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError as exc:
                raise LoadOrderTraceabilityError(f"La {label} no es valida.") from exc
        raise LoadOrderTraceabilityError(f"La {label} no es valida.")

    def _apply_item(self, item: dict, order: LoadOrder, reason: str | None) -> int:
        target = item["target"]
        before = {field: getattr(target, field) for field in TRACEABILITY_FIELDS}
        after = {
            "lote": item["lote"],
            "fecha_elaboracion": item["fecha_elaboracion"],
            "fecha_envasado": item["fecha_envasado"],
        }
        if before == after:
            return 0

        for field in TRACEABILITY_FIELDS:
            setattr(target, field, after[field])
        model = type(target)
        target.save(
            only=[
                model.lote,
                model.fecha_elaboracion,
                model.fecha_envasado,
            ]
        )
        self.audit_service.record(
            user=self.current_user,
            module="Ordenes de carga",
            action="editar lote/fecha",
            record_ref=f"{model.__name__}:{target.id}",
            old_value=self._serialize(before),
            new_value={
                "orden": order.order_number,
                "tipo": item["kind"],
                **self._serialize(after),
            },
            observation=reason,
        )
        return 1

    @staticmethod
    def _serialize(values: dict) -> dict:
        return {
            field: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else value
            )
            for field, value in values.items()
        }


__all__ = [
    "LINE",
    "LOOSE_CONTENT",
    "LoadOrderTraceabilityError",
    "LoadOrderTraceabilityService",
    "MAX_LOTE_LENGTH",
    "PALLET_CONTENT",
]

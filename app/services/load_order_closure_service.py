from __future__ import annotations

from peewee import IntegrityError

from app.config.database import database_proxy
from app.models.base import utc_now
from app.models.load_orders import LoadOrder, LoadOrderClosure
from app.services.audit_service import AuditService
from app.services.load_order_service import LoadOrderService


class LoadOrderClosureError(ValueError):
    pass


class LoadOrderClosureService:
    """Own the persisted close/reopen lifecycle of an issued load order."""

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.load_orders = LoadOrderService(
            current_user=current_user,
            audit_service=self.audit_service,
        )

    def close_order(
        self,
        order: LoadOrder,
        *,
        observations: str | None = None,
    ) -> LoadOrderClosure:
        order = self._require_order(order)
        if order.status != LoadOrder.STATUS_ISSUED:
            raise LoadOrderClosureError("Solo se pueden cerrar ordenes emitidas.")

        normalized_observations = (observations or "").strip() or None
        with database_proxy.atomic():
            order = LoadOrder.get_by_id(order.id)
            if order.status != LoadOrder.STATUS_ISSUED:
                raise LoadOrderClosureError("Solo se pueden cerrar ordenes emitidas.")
            if self.active_closure(order) is not None:
                raise LoadOrderClosureError("La orden ya tiene un cierre de entrega activo.")
            try:
                closure = LoadOrderClosure.create(
                    order=order,
                    status=LoadOrderClosure.STATUS_ACTIVE,
                    active_marker=True,
                    closed_by=self.current_user,
                    observations=normalized_observations,
                )
            except IntegrityError as exc:
                raise LoadOrderClosureError("La orden ya tiene un cierre de entrega activo.") from exc
            self.load_orders._change_status(
                order,
                LoadOrder.STATUS_CLOSED,
                reason="Cierre de entrega",
            )
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action="cerrar entrega",
                record_ref=f"LoadOrderClosure:{closure.id}",
                new_value={
                    "order_id": order.id,
                    "status": closure.status,
                    "observations": closure.observations,
                },
            )
        return LoadOrderClosure.get_by_id(closure.id)

    def reopen_order(self, order: LoadOrder, *, reason: str) -> LoadOrder:
        order = self._require_order(order)
        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise LoadOrderClosureError("Debe indicar el motivo de reapertura.")

        with database_proxy.atomic():
            order = LoadOrder.get_by_id(order.id)
            if order.status != LoadOrder.STATUS_CLOSED:
                raise LoadOrderClosureError("Solo se pueden reabrir ordenes cerradas.")
            closure = self.active_closure(order)
            if closure is None:
                raise LoadOrderClosureError("La orden cerrada no tiene un cierre de entrega activo.")

            self.load_orders._change_status(
                order,
                LoadOrder.STATUS_ISSUED,
                reason=f"Reapertura de entrega: {normalized_reason}",
            )
            reopened_at = utc_now()
            closure.status = LoadOrderClosure.STATUS_REOPENED
            closure.active_marker = None
            closure.reopened_at = reopened_at
            closure.reopened_by = self.current_user
            closure.reopen_reason = normalized_reason
            closure.save()
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action="reabrir entrega",
                record_ref=f"LoadOrderClosure:{closure.id}",
                old_value={"status": LoadOrderClosure.STATUS_ACTIVE},
                new_value={
                    "order_id": order.id,
                    "status": closure.status,
                    "reopened_at": reopened_at.isoformat(timespec="seconds"),
                    "reopened_by": self.current_user,
                    "reason": normalized_reason,
                },
            )
        return LoadOrder.get_by_id(order.id)

    def active_closure(self, order: LoadOrder) -> LoadOrderClosure | None:
        order = self._require_order(order)
        return (
            LoadOrderClosure.select()
            .where(
                (LoadOrderClosure.order == order)
                & (LoadOrderClosure.active_marker == True)  # noqa: E712
                & (LoadOrderClosure.status == LoadOrderClosure.STATUS_ACTIVE)
            )
            .order_by(LoadOrderClosure.id.desc())
            .first()
        )

    def _require_order(self, order: LoadOrder) -> LoadOrder:
        if order is None or not isinstance(order, LoadOrder) or order.id is None:
            raise LoadOrderClosureError("Debe seleccionar una orden valida.")
        try:
            return LoadOrder.get_by_id(order.id)
        except LoadOrder.DoesNotExist as exc:
            raise LoadOrderClosureError("La orden seleccionada no existe.") from exc

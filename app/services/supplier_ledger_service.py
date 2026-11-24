"""Libro de movimientos e imputaciones de la cuenta corriente de proveedores (#940).

Con el maestro (#938) y los documentos importados (#939) la posicion con cada
productor existe, pero el legacy descontaba los pagos a mano del ``SALDO`` del
documento, sin rastro. Este servicio es el lugar donde FEMAG Desktop registra:

- el **saldo inicial** de cada documento importado (``opening_balance``): lo
  que el legacy tenia pendiente al corte. Los pagos que el legacy ya habia
  descontado quedan dentro de ese saldo; no se inventan como pagos;
- el **pago** a un proveedor, con su imputacion explicita a uno o varios
  tickets, parcial o total;
- la **anulacion** de un pago, que revierte solo las imputaciones de ese pago.

El saldo de un proveedor a cualquier fecha es la suma de sus movimientos hasta
esa fecha. Positivo es lo que la empresa le debe al proveedor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from peewee import JOIN, IntegrityError, fn

from app.models.base import utc_now
from app.models.security import User
from app.models.suppliers import (
    Supplier,
    SupplierAccountMovement,
    SupplierDocument,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from app.models.system import NumberSequence
from app.services.audit_service import AuditService
from app.services.permission_service import PermissionService

PAYMENT_SEQUENCE_NAME = "supplier_payment_order"
AUDIT_MODULE = "Cuenta corriente proveedores"
# Item de menu cuyo permiso gobierna la pantalla y sus acciones (#941).
MENU_SECTION = "Producción"
MENU_TITLE = "Cuenta corriente productores"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


class SupplierLedgerError(ValueError):
    pass


@dataclass(frozen=True)
class AllocationRequest:
    """Lo que se quiere imputar de un pago a un documento."""

    document: SupplierDocument
    amount: Decimal


def _money(value, *, field: str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SupplierLedgerError(f"Importe invalido en {field}.") from exc
    if not amount.is_finite():
        raise SupplierLedgerError(f"Importe invalido en {field}.")
    return amount


def _sum(query) -> Decimal:
    value = query.scalar()
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def opening_sign(document: SupplierDocument) -> int:
    """El ticket es deuda de la empresa (+); el pagare, del productor (-)."""
    return 1 if document.kind == SupplierDocument.KIND_TICKET else -1


def _has_menu_permission(user: User | None, action: str) -> bool:
    if user is None or not getattr(user, "active", False):
        return False
    if PermissionService.is_administrator(user):
        return True
    return PermissionService().has_permission(user, MENU_SECTION, action, MENU_TITLE)


def can_register_payments(user: User | None) -> bool:
    return _has_menu_permission(user, "crear")


def can_annul_payments(user: User | None) -> bool:
    return _has_menu_permission(user, "anular")


class SupplierLedgerService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        current_user = (current_user or "").strip()
        if not current_user:
            raise SupplierLedgerError("El libro necesita un usuario responsable.")
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    # ------------------------------------------------------------------
    # Saldo inicial
    # ------------------------------------------------------------------
    def open_ledger_from_imports(self, cutoff: date | None = None) -> int:
        """Crea el saldo inicial de cada documento importado que no lo tenga.

        Es idempotente: correrlo dos veces no duplica movimientos. Devuelve la
        cantidad de saldos iniciales creados.
        """
        pending = (
            SupplierDocument.select()
            .join(
                SupplierAccountMovement,
                JOIN.LEFT_OUTER,
                on=(
                    (SupplierAccountMovement.document == SupplierDocument.id)
                    & (
                        SupplierAccountMovement.movement_type
                        == SupplierAccountMovement.TYPE_OPENING_BALANCE
                    )
                ),
            )
            .where(SupplierAccountMovement.id.is_null())
            .order_by(SupplierDocument.id)
        )
        created = 0
        database = SupplierAccountMovement._meta.database
        with database.atomic():
            for document in pending:
                if self._ensure_opening(document, cutoff=cutoff)[1]:
                    created += 1
        return created

    def _ensure_opening(
        self, document: SupplierDocument, *, cutoff: date | None = None
    ) -> tuple[SupplierAccountMovement, bool]:
        source_ref = f"SupplierDocument:{document.id}:opening"
        existing = SupplierAccountMovement.get_or_none(
            SupplierAccountMovement.source_ref == source_ref
        )
        if existing is not None:
            return existing, False
        imported_at = document.imported_at
        movement_date = cutoff or (
            imported_at.date() if hasattr(imported_at, "date") else date.today()
        )
        balance = Decimal(str(document.balance)).quantize(CENT)
        movement = SupplierAccountMovement.create(
            supplier=document.supplier_id,
            document=document,
            movement_type=SupplierAccountMovement.TYPE_OPENING_BALANCE,
            amount=balance * opening_sign(document),
            currency=document.currency,
            movement_date=movement_date,
            description=(
                f"Saldo inicial importado - {document.kind_label} {document.source_code}"
            )[:200],
            observations=(
                "Saldo pendiente en el legacy al corte. Los pagos que el legacy "
                "ya habia descontado no se reconstruyen: no hay dato de que pago "
                "cancelo que documento."
            ),
            source_ref=source_ref,
            created_by=self.current_user,
        )
        return movement, True

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    @staticmethod
    def allocated_amount(document: SupplierDocument) -> Decimal:
        """Lo imputado al documento por pagos activos."""
        return _sum(
            SupplierPaymentAllocation.select(fn.SUM(SupplierPaymentAllocation.amount))
            .join(SupplierPayment)
            .where(
                SupplierPaymentAllocation.document == document,
                SupplierPayment.status == SupplierPayment.STATUS_ACTIVE,
            )
        )

    @classmethod
    def document_pending(cls, document: SupplierDocument) -> Decimal:
        """Saldo pendiente del documento: importado menos imputaciones activas."""
        balance = Decimal(str(document.balance)).quantize(CENT)
        return balance - cls.allocated_amount(document)

    @staticmethod
    def balance(supplier: Supplier, at: date | None = None) -> Decimal:
        """Saldo del proveedor a una fecha, como suma de sus movimientos."""
        query = SupplierAccountMovement.select(
            fn.SUM(SupplierAccountMovement.amount)
        ).where(SupplierAccountMovement.supplier == supplier)
        if at is not None:
            query = query.where(SupplierAccountMovement.movement_date <= at)
        return _sum(query)

    @staticmethod
    def balances(at: date | None = None) -> dict[int, Decimal]:
        """Saldo de cada proveedor con movimientos, a una fecha."""
        query = SupplierAccountMovement.select(
            SupplierAccountMovement.supplier,
            fn.SUM(SupplierAccountMovement.amount).alias("total"),
        ).group_by(SupplierAccountMovement.supplier)
        if at is not None:
            query = query.where(SupplierAccountMovement.movement_date <= at)
        return {
            row.supplier_id: Decimal(str(row.total or 0)).quantize(CENT)
            for row in query
        }

    # ------------------------------------------------------------------
    # Pagos
    # ------------------------------------------------------------------
    def register_payment(
        self,
        *,
        supplier: Supplier,
        amount,
        method: str,
        allocations: list[AllocationRequest],
        payment_date: date | None = None,
        reference: str | None = None,
        observations: str | None = None,
        idempotency_key: str | None = None,
    ) -> SupplierPayment:
        if supplier is None or not isinstance(supplier, Supplier):
            raise SupplierLedgerError("Debe seleccionar un proveedor.")
        total = _money(amount, field="el pago")
        if total <= ZERO:
            raise SupplierLedgerError("El importe del pago debe ser mayor a cero.")
        method = (method or "").strip()
        if method not in SupplierPayment.METHODS:
            raise SupplierLedgerError(f"Medio de pago invalido: {method!r}.")
        idempotency_key = (idempotency_key or "").strip() or None
        if idempotency_key and len(idempotency_key) > 64:
            raise SupplierLedgerError("La clave de idempotencia es demasiado larga.")
        reference = (reference or "").strip() or None
        observations = (observations or "").strip() or None
        normalized = self._normalize_allocations(supplier, allocations, total)

        database = SupplierPayment._meta.database
        try:
            with database.atomic():
                if idempotency_key:
                    existing = self._payment_for_key(idempotency_key)
                    if existing is not None:
                        return self._resolve_idempotent(existing, supplier, total)
                for document, allocation in normalized:
                    pending = self.document_pending(document)
                    if allocation > pending:
                        raise SupplierLedgerError(
                            f"El {document.kind_label.lower()} {document.source_code} "
                            f"tiene un saldo pendiente de {pending:,.2f}: imputarle "
                            f"{allocation:,.2f} lo dejaria en negativo."
                        )
                payment = SupplierPayment.create(
                    number=self._next_payment_number(),
                    idempotency_key=idempotency_key,
                    supplier=supplier,
                    payment_date=payment_date or date.today(),
                    amount=total,
                    method=method,
                    reference=reference,
                    observations=observations,
                    created_by=self.current_user,
                )
                for sequence, (document, allocation) in enumerate(normalized, start=1):
                    self._ensure_opening(document)
                    SupplierPaymentAllocation.create(
                        payment=payment,
                        document=document,
                        amount=allocation,
                        sequence=sequence,
                    )
                    SupplierAccountMovement.create(
                        supplier=supplier,
                        document=document,
                        payment=payment,
                        movement_type=SupplierAccountMovement.TYPE_PAYMENT,
                        amount=-allocation,
                        currency=payment.currency,
                        movement_date=payment.payment_date,
                        description=(
                            f"Pago {payment.number} - imputado a "
                            f"{document.kind_label.lower()} {document.source_code}"
                        )[:200],
                        observations=observations
                        or f"Pago {method} registrado por {self.current_user}.",
                        source_ref=f"SupplierPayment:{payment.id}:document:{document.id}",
                        created_by=self.current_user,
                    )
                self.audit_service.record(
                    user=self.current_user,
                    module=AUDIT_MODULE,
                    action="registrar_pago_proveedor",
                    record_ref=f"SupplierPayment:{payment.id}",
                    new_value={
                        "supplier_id": supplier.id,
                        "number": payment.number,
                        "amount": str(total),
                        "method": method,
                        "payment_date": payment.payment_date.isoformat(),
                        "reference": reference,
                        "allocations": [
                            {"document_id": document.id, "amount": str(allocation)}
                            for document, allocation in normalized
                        ],
                    },
                )
        except IntegrityError as exc:
            if idempotency_key:
                existing = self._payment_for_key(idempotency_key)
                if existing is not None:
                    return self._resolve_idempotent(existing, supplier, total)
            raise SupplierLedgerError(f"No se pudo registrar el pago: {exc}") from exc
        return payment

    @staticmethod
    def _normalize_allocations(
        supplier: Supplier, allocations: list[AllocationRequest], total: Decimal
    ) -> list[tuple[SupplierDocument, Decimal]]:
        if not allocations:
            raise SupplierLedgerError(
                "El pago debe imputarse al menos a un documento."
            )
        normalized: list[tuple[SupplierDocument, Decimal]] = []
        seen: set[int] = set()
        for index, request in enumerate(allocations, start=1):
            document = getattr(request, "document", None)
            if document is None or not isinstance(document, SupplierDocument):
                raise SupplierLedgerError(f"La imputacion {index} no tiene documento.")
            document = SupplierDocument.get_by_id(document.id)
            if document.supplier_id != supplier.id:
                raise SupplierLedgerError(
                    f"El documento {document.source_code} no es de este proveedor."
                )
            if document.kind != SupplierDocument.KIND_TICKET:
                raise SupplierLedgerError(
                    f"El {document.kind_label.lower()} {document.source_code} es deuda "
                    "del productor con la empresa: un pago al productor no lo cancela."
                )
            if document.id in seen:
                raise SupplierLedgerError(
                    f"El documento {document.source_code} esta imputado dos veces."
                )
            seen.add(document.id)
            amount = _money(request.amount, field=f"la imputacion {index}")
            if amount <= ZERO:
                raise SupplierLedgerError(
                    f"La imputacion {index} debe ser mayor a cero."
                )
            normalized.append((document, amount))
        allocated = sum((amount for _, amount in normalized), ZERO)
        if allocated != total:
            raise SupplierLedgerError(
                f"Las imputaciones suman {allocated:,.2f} y el pago es de "
                f"{total:,.2f}: tienen que coincidir."
            )
        return normalized

    @staticmethod
    def _payment_for_key(idempotency_key: str) -> SupplierPayment | None:
        return SupplierPayment.get_or_none(
            SupplierPayment.idempotency_key == idempotency_key
        )

    @staticmethod
    def _resolve_idempotent(
        existing: SupplierPayment, supplier: Supplier, total: Decimal
    ) -> SupplierPayment:
        if existing.supplier_id != supplier.id or Decimal(str(existing.amount)) != total:
            raise SupplierLedgerError("La clave de idempotencia ya fue usada por otro pago.")
        if existing.status == SupplierPayment.STATUS_ANNULLED:
            raise SupplierLedgerError("El pago ya fue registrado y anulado.")
        return existing

    def _next_payment_number(self) -> str:
        sequence, _ = NumberSequence.get_or_create(
            name=PAYMENT_SEQUENCE_NAME, defaults={"current_number": 0}
        )
        for _ in range(5):
            updated = (
                NumberSequence.update(current_number=NumberSequence.current_number + 1)
                .where(
                    NumberSequence.id == sequence.id,
                    NumberSequence.current_number == sequence.current_number,
                )
                .execute()
            )
            if updated:
                return f"OPP-{sequence.current_number + 1:08d}"
            sequence = NumberSequence.get_by_id(sequence.id)
        raise SupplierLedgerError("No se pudo obtener el siguiente numero de pago.")

    # ------------------------------------------------------------------
    # Anulacion
    # ------------------------------------------------------------------
    def annul_payment(
        self,
        payment: SupplierPayment,
        *,
        authorized_by: User,
        reason: str | None = None,
    ) -> SupplierPayment:
        if payment is None or not isinstance(payment, SupplierPayment):
            raise SupplierLedgerError("Debe seleccionar un pago.")
        if authorized_by is None or not isinstance(authorized_by, User) or not authorized_by.active:
            raise PermissionError("La anulacion requiere un usuario habilitado.")
        if authorized_by.username != self.current_user:
            raise PermissionError(
                "La anulacion debe realizarse con la sesion del usuario autorizado."
            )
        if not can_annul_payments(authorized_by):
            raise PermissionError("No tiene permiso para anular pagos a productores.")
        reason = (reason or "").strip()
        if not reason:
            raise SupplierLedgerError("Debe indicar el motivo de la anulacion.")

        database = SupplierPayment._meta.database
        with database.atomic():
            payment = SupplierPayment.get_by_id(payment.id)
            if payment.status == SupplierPayment.STATUS_ANNULLED:
                raise SupplierLedgerError("El pago ya esta anulado.")
            originals = list(
                SupplierAccountMovement.select()
                .where(
                    SupplierAccountMovement.payment == payment,
                    SupplierAccountMovement.movement_type
                    == SupplierAccountMovement.TYPE_PAYMENT,
                )
                .order_by(SupplierAccountMovement.id)
            )
            if not originals:
                raise SupplierLedgerError("No se encontraron los movimientos del pago.")
            annulled_at = utc_now()
            reversal_ids = []
            for original in originals:
                reversal = SupplierAccountMovement.create(
                    supplier=original.supplier_id,
                    document=original.document_id,
                    payment=payment,
                    movement_type=SupplierAccountMovement.TYPE_PAYMENT_REVERSAL,
                    amount=-Decimal(str(original.amount)),
                    currency=original.currency,
                    movement_date=annulled_at.date(),
                    description=f"Anulacion pago {payment.number}"[:200],
                    observations=reason,
                    source_ref=f"{original.source_ref}:annulment",
                    is_reversal=True,
                    reverses=original,
                    created_by=self.current_user,
                )
                reversal_ids.append(reversal.id)
            payment.status = SupplierPayment.STATUS_ANNULLED
            payment.annulled_at = annulled_at
            payment.annulled_by = authorized_by.username
            payment.annulment_reason = reason
            payment.save()
            self.audit_service.record(
                user=self.current_user,
                module=AUDIT_MODULE,
                action="anular_pago_proveedor",
                record_ref=f"SupplierPayment:{payment.id}",
                old_value={"status": SupplierPayment.STATUS_ACTIVE, "amount": str(payment.amount)},
                new_value={
                    "status": payment.status,
                    "annulled_at": annulled_at.isoformat(timespec="seconds"),
                    "annulled_by": authorized_by.username,
                    "annulment_reason": reason,
                    "reversal_movement_ids": reversal_ids,
                },
            )
        return payment

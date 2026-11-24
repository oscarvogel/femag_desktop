"""Consulta de la posicion con los productores para la pantalla (#941).

Lee los documentos importados (#939) y las imputaciones de pagos del libro
(#940) y arma lo que la pantalla muestra: un renglon por productor con lo que
la empresa le debe (tickets) y lo que el productor le debe a la empresa
(pagares), el detalle de sus documentos y sus pagos.

El pendiente de un documento es su saldo importado menos lo imputado por pagos
activos: es el mismo numero que suma el libro, asi que la pantalla y el libro
no pueden divergir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from peewee import fn

from app.models.suppliers import (
    Supplier,
    SupplierDocument,
    SupplierDocumentExclusion,
    SupplierLegacyCode,
    SupplierPayment,
    SupplierPaymentAllocation,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _dec(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT)


@dataclass(frozen=True)
class SupplierPositionFilters:
    supplier_id: int | None = None
    kind: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    only_with_balance: bool = True


@dataclass(frozen=True)
class SupplierDocumentRow:
    document_id: int
    supplier_id: int
    kind: str
    kind_label: str
    code: str
    issued_at: date | None
    date_inferred: bool
    amount: Decimal
    imported_balance: Decimal
    paid: Decimal
    pending: Decimal

    @property
    def signed_pending(self) -> Decimal:
        """Positivo si la empresa debe (ticket), negativo si debe el productor."""
        if self.kind == SupplierDocument.KIND_TICKET:
            return self.pending
        return -self.pending


@dataclass
class SupplierPositionRow:
    supplier_id: int
    name: str
    codes: str
    payable: Decimal = ZERO
    receivable: Decimal = ZERO
    oldest_date: date | None = None
    documents: int = 0

    @property
    def net(self) -> Decimal:
        return self.payable - self.receivable

    def age_days(self, today: date | None = None) -> int | None:
        if self.oldest_date is None:
            return None
        return ((today or date.today()) - self.oldest_date).days


@dataclass
class SupplierPositionResult:
    rows: list[SupplierPositionRow] = field(default_factory=list)
    excluded_count: int = 0
    excluded_amount: Decimal = ZERO
    imported_documents: int = 0

    @property
    def payable(self) -> Decimal:
        return sum((row.payable for row in self.rows), ZERO)

    @property
    def receivable(self) -> Decimal:
        return sum((row.receivable for row in self.rows), ZERO)

    @property
    def net(self) -> Decimal:
        return self.payable - self.receivable


class SupplierPositionService:
    @staticmethod
    def suppliers_with_documents() -> list[Supplier]:
        """Productores que tienen al menos un documento importado."""
        return list(
            Supplier.select()
            .where(Supplier.id.in_(SupplierDocument.select(SupplierDocument.supplier)))
            .order_by(Supplier.name)
        )

    @staticmethod
    def _paid_by_document(document_ids: list[int] | None = None) -> dict[int, Decimal]:
        query = (
            SupplierPaymentAllocation.select(
                SupplierPaymentAllocation.document,
                fn.SUM(SupplierPaymentAllocation.amount).alias("total"),
            )
            .join(SupplierPayment)
            .where(SupplierPayment.status == SupplierPayment.STATUS_ACTIVE)
            .group_by(SupplierPaymentAllocation.document)
        )
        if document_ids is not None:
            if not document_ids:
                return {}
            query = query.where(SupplierPaymentAllocation.document.in_(document_ids))
        return {row.document_id: _dec(row.total) for row in query}

    def documents(self, filters: SupplierPositionFilters) -> list[SupplierDocumentRow]:
        query = SupplierDocument.select()
        if filters.supplier_id is not None:
            query = query.where(SupplierDocument.supplier == filters.supplier_id)
        if filters.kind:
            query = query.where(SupplierDocument.kind == filters.kind)
        if filters.date_from is not None:
            query = query.where(SupplierDocument.issued_at >= filters.date_from)
        if filters.date_to is not None:
            query = query.where(SupplierDocument.issued_at <= filters.date_to)
        documents = list(query.order_by(SupplierDocument.issued_at, SupplierDocument.id))
        paid = self._paid_by_document(
            [document.id for document in documents] if filters.supplier_id else None
        )
        rows = []
        for document in documents:
            imported = _dec(document.balance)
            paid_amount = paid.get(document.id, ZERO)
            pending = imported - paid_amount
            if filters.only_with_balance and pending == ZERO:
                continue
            rows.append(
                SupplierDocumentRow(
                    document_id=document.id,
                    supplier_id=document.supplier_id,
                    kind=document.kind,
                    kind_label=document.kind_label,
                    code=document.source_code,
                    issued_at=document.issued_at,
                    date_inferred=bool(document.date_inferred),
                    amount=_dec(document.amount),
                    imported_balance=imported,
                    paid=paid_amount,
                    pending=pending,
                )
            )
        return rows

    def position(
        self,
        filters: SupplierPositionFilters,
        *,
        documents: list[SupplierDocumentRow] | None = None,
    ) -> SupplierPositionResult:
        if documents is None:
            documents = self.documents(filters)
        supplier_ids = {row.supplier_id for row in documents}
        names = {
            supplier.id: supplier.name
            for supplier in Supplier.select().where(Supplier.id.in_(list(supplier_ids)))
        } if supplier_ids else {}
        codes: dict[int, list[str]] = defaultdict(list)
        if supplier_ids:
            for ficha in SupplierLegacyCode.select().where(
                SupplierLegacyCode.supplier.in_(list(supplier_ids))
            ):
                codes[ficha.supplier_id].append(ficha.code)

        by_supplier: dict[int, SupplierPositionRow] = {}
        for document in documents:
            row = by_supplier.get(document.supplier_id)
            if row is None:
                row = SupplierPositionRow(
                    supplier_id=document.supplier_id,
                    name=names.get(document.supplier_id, ""),
                    codes=", ".join(sorted(codes.get(document.supplier_id, []))),
                )
                by_supplier[document.supplier_id] = row
            if document.kind == SupplierDocument.KIND_TICKET:
                row.payable += document.pending
            else:
                row.receivable += document.pending
            row.documents += 1
            if document.pending != ZERO and document.issued_at is not None:
                if row.oldest_date is None or document.issued_at < row.oldest_date:
                    row.oldest_date = document.issued_at

        rows = sorted(by_supplier.values(), key=lambda item: (-item.net, item.name))
        excluded_count, excluded_amount = self.exclusions_summary()
        return SupplierPositionResult(
            rows=rows,
            excluded_count=excluded_count,
            excluded_amount=excluded_amount,
            imported_documents=SupplierDocument.select().count(),
        )

    @staticmethod
    def exclusions_summary() -> tuple[int, Decimal]:
        row = SupplierDocumentExclusion.select(
            fn.COUNT(SupplierDocumentExclusion.id).alias("count"),
            fn.SUM(SupplierDocumentExclusion.amount).alias("total"),
        ).dicts().get()
        return int(row["count"] or 0), _dec(row["total"])

    @staticmethod
    def payments(supplier_id: int) -> list[SupplierPayment]:
        return list(
            SupplierPayment.select()
            .where(SupplierPayment.supplier == supplier_id)
            .order_by(SupplierPayment.payment_date.desc(), SupplierPayment.id.desc())
        )

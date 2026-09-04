from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.models.accounting import ClientAccountMovement
from app.models.payments import ClientPayment, ClientPaymentDetail, PaymentMethod


@dataclass(frozen=True)
class DailyCollectionsFilters:
    start: date
    end: date
    client_id: int | None = None
    movement_type: str | None = None
    payment_method: str | None = None
    currency: str | None = "ARS"
    created_by: str | None = None
    reversals_only: bool = False


@dataclass(frozen=True)
class DailyCollectionsTotals:
    collected: float
    active_payments: int
    clients: int
    debit: float
    credit: float
    movements: int


@dataclass(frozen=True)
class DailyCollectionsReportResult:
    filters: DailyCollectionsFilters
    collection_rows: tuple[dict, ...]
    movement_rows: tuple[dict, ...]
    totals: DailyCollectionsTotals
    collections_by_method: tuple[tuple[str, float], ...]


class DailyCollectionsReportService:
    """Auditable collections and client-account movements for an operational period."""

    def report(self, filters: DailyCollectionsFilters) -> DailyCollectionsReportResult:
        if filters.start > filters.end:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

        collection_rows = self._collection_rows(filters)
        movement_rows = self._movement_rows(filters)
        effective_collections = [
            row for row in collection_rows if row["status"] == ClientPayment.STATUS_ACTIVE
        ]
        by_method: dict[str, float] = defaultdict(float)
        for row in effective_collections:
            by_method[row["payment_method_name"]] += float(row["amount"] or 0)

        return DailyCollectionsReportResult(
            filters=filters,
            collection_rows=tuple(collection_rows),
            movement_rows=tuple(movement_rows),
            totals=DailyCollectionsTotals(
                collected=round(sum(float(row["amount"] or 0) for row in effective_collections), 2),
                active_payments=len({row["payment_id"] for row in effective_collections}),
                clients=len({row["client_id"] for row in effective_collections}),
                debit=round(sum(float(row["debit"] or 0) for row in movement_rows), 2),
                credit=round(sum(float(row["credit"] or 0) for row in movement_rows), 2),
                movements=len(movement_rows),
            ),
            collections_by_method=tuple(
                sorted((name, round(amount, 2)) for name, amount in by_method.items())
            ),
        )

    def _collection_rows(self, filters: DailyCollectionsFilters) -> list[dict]:
        query = (
            ClientPayment.select()
            .where(
                ClientPayment.payment_date >= filters.start,
                ClientPayment.payment_date <= filters.end,
            )
            .order_by(ClientPayment.payment_date, ClientPayment.id)
        )
        if filters.client_id is not None:
            query = query.where(ClientPayment.client == filters.client_id)
        if filters.created_by:
            query = query.where(ClientPayment.created_by == filters.created_by)

        rows: list[dict] = []
        for payment in query:
            if filters.reversals_only and payment.status != ClientPayment.STATUS_ANNULLED:
                continue
            order = payment.closure.order if payment.closure_id else None
            carrier = order.carrier if order is not None and order.carrier_id else None
            details = list(
                ClientPaymentDetail.select(ClientPaymentDetail, PaymentMethod)
                .join(PaymentMethod)
                .where(ClientPaymentDetail.payment == payment)
                .order_by(ClientPaymentDetail.sequence)
            )
            if details:
                for detail in details:
                    method = detail.payment_method
                    if filters.payment_method and method.code != filters.payment_method:
                        continue
                    rows.append(
                        self._collection_row(
                            payment=payment,
                            amount=float(detail.amount or 0),
                            method_code=method.code,
                            method_name=method.name,
                            reference=detail.reference,
                            detail_observations=detail.observations,
                            order=order,
                            carrier=carrier,
                        )
                    )
            else:
                method_code = str(payment.method or "")
                if filters.payment_method and method_code != filters.payment_method:
                    continue
                rows.append(
                    self._collection_row(
                        payment=payment,
                        amount=float(payment.amount or 0),
                        method_code=method_code,
                        method_name=self._legacy_method_name(method_code),
                        reference=payment.reference,
                        detail_observations=None,
                        order=order,
                        carrier=carrier,
                    )
                )
        return rows

    @staticmethod
    def _collection_row(
        *,
        payment: ClientPayment,
        amount: float,
        method_code: str,
        method_name: str,
        reference: str | None,
        detail_observations: str | None,
        order,
        carrier,
    ) -> dict:
        return {
            "payment_id": payment.id,
            "date": payment.payment_date,
            "receipt_number": payment.receipt_number,
            "client_id": payment.client_id,
            "client_name": payment.client.name,
            "amount": round(amount, 2),
            "payment_total": round(float(payment.amount or 0), 2),
            "payment_method": method_code,
            "payment_method_name": method_name,
            "reference": reference or "",
            "order_id": order.id if order is not None else None,
            "order_number": order.order_number if order is not None else None,
            "carrier_name": carrier.name if carrier is not None else "",
            "created_by": payment.created_by or "",
            "observations": detail_observations or payment.observations or "",
            "status": payment.status,
            "annulled_by": payment.annulled_by or "",
            "annulment_reason": payment.annulment_reason or "",
        }

    def _movement_rows(self, filters: DailyCollectionsFilters) -> list[dict]:
        query = ClientAccountMovement.select().order_by(
            ClientAccountMovement.client,
            ClientAccountMovement.movement_date,
            ClientAccountMovement.id,
        )
        if filters.client_id is not None:
            query = query.where(ClientAccountMovement.client == filters.client_id)
        if filters.movement_type:
            query = query.where(ClientAccountMovement.movement_type == filters.movement_type)
        if filters.currency:
            query = query.where(ClientAccountMovement.currency == filters.currency)
        if filters.created_by:
            query = query.where(ClientAccountMovement.created_by == filters.created_by)
        if filters.reversals_only:
            query = query.where(ClientAccountMovement.is_reversal == True)  # noqa: E712

        candidates = list(query)
        balances = self._running_balances(candidates, filters.end)
        rows: list[dict] = []
        for movement in candidates:
            effective_date = self._movement_effective_date(movement)
            if effective_date is None or effective_date < filters.start or effective_date > filters.end:
                continue
            total = round(float(movement.total_amount or 0), 2)
            rows.append(
                {
                    "movement_id": movement.id,
                    "date": effective_date,
                    "client_id": movement.client_id,
                    "client_name": movement.client.name,
                    "movement_type": movement.movement_type,
                    "description": movement.description,
                    "reference": movement.reference or "",
                    "source_ref": movement.source_ref,
                    "debit": max(total, 0.0),
                    "credit": max(-total, 0.0),
                    "balance": balances.get(movement.id, 0.0),
                    "currency": movement.currency,
                    "due_date": movement.due_date,
                    "created_by": movement.created_by or "",
                    "order_id": movement.load_order_id,
                    "order_number": movement.load_order.order_number if movement.load_order_id else None,
                    "payment_id": movement.payment_id,
                    "is_reversal": bool(movement.is_reversal),
                    "reverses_id": movement.reverses_id,
                }
            )
        rows.sort(key=lambda row: (row["date"], row["client_name"].casefold(), row["movement_id"]))
        return rows

    def _running_balances(self, filtered_candidates: list[ClientAccountMovement], as_of: date) -> dict[int, float]:
        wanted_ids = {movement.id for movement in filtered_candidates}
        client_currency = {
            (movement.client_id, movement.currency)
            for movement in filtered_candidates
        }
        balance_by_key: dict[tuple[int, str], float] = defaultdict(float)
        result: dict[int, float] = {}
        all_movements = [
            movement
            for movement in ClientAccountMovement.select()
            if (movement.client_id, movement.currency) in client_currency
        ]
        dated_movements = [
            (self._movement_effective_date(movement), movement)
            for movement in all_movements
        ]
        dated_movements = [
            (effective_date, movement)
            for effective_date, movement in dated_movements
            if effective_date is not None and effective_date <= as_of
        ]
        dated_movements.sort(
            key=lambda pair: (
                pair[1].client_id,
                pair[1].currency,
                pair[0],
                pair[1].id,
            )
        )
        for _effective_date, movement in dated_movements:
            key = (movement.client_id, movement.currency)
            balance_by_key[key] += float(movement.total_amount or 0)
            if movement.id in wanted_ids:
                result[movement.id] = round(balance_by_key[key], 2)
        return result

    @staticmethod
    def _movement_effective_date(movement: ClientAccountMovement) -> date | None:
        if movement.movement_date is not None:
            return movement.movement_date
        if movement.payment_id and movement.payment is not None:
            if movement.is_reversal and movement.payment.annulled_at is not None:
                return movement.payment.annulled_at.date()
            return movement.payment.payment_date
        if movement.load_order_id and movement.load_order is not None:
            return movement.load_order.date
        return None

    @staticmethod
    def _legacy_method_name(code: str) -> str:
        labels = {
            ClientPayment.METHOD_CASH: "Efectivo",
            ClientPayment.METHOD_TRANSFER: "Transferencia",
            ClientPayment.METHOD_CHECK: "Cheque",
            ClientPayment.METHOD_RETENTION: "Retenciones / Percepciones",
            ClientPayment.METHOD_HOLISTOR: "Holistor",
            ClientPayment.METHOD_OTHER: "Otros",
            "multiple": "Múltiples medios",
        }
        return labels.get(code, code or "Sin especificar")

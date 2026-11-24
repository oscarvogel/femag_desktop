from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.reports.collection_due_report import CollectionDueFilters, CollectionDueReportService
from app.services.ledger_query_service import client_balances


_MONEY_QUANTUM = Decimal("0.01")

_BUCKET_OVERDUE = "overdue"
_BUCKET_TODAY = "today"
_BUCKET_NEXT_7 = "next_7"
_BUCKET_NEXT_30 = "next_30"


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def client_balances_by_id() -> dict[int, Decimal]:
    """
    Saldo neto por cliente en cuenta corriente (pagos y creditos descontados).

    Reusa `ledger_query_service.client_balances()` para no duplicar la regla
    contable: es la misma suma que muestra la grilla de Cuenta Corriente.
    """
    return {
        entry["client"].id: _money(entry["balance"])
        for entry in client_balances()
    }


@dataclass(frozen=True)
class CollectionExposure:
    """
    Exposición por cliente de cada ventana de vencimiento.

    Es lo que se puede exigir hoy de cada cliente, no la suma bruta de los
    documentos vencidos. Un cliente que ya pagó (o que tiene credito) no aporta
    importe a ninguna tarjeta, aunque conserve documentos vencidos en el
    historial.
    """

    overdue_amount: float = 0.0
    overdue_clients: int = 0
    due_today_amount: float = 0.0
    due_today_clients: int = 0
    next_7_amount: float = 0.0
    next_7_clients: int = 0
    next_30_amount: float = 0.0
    next_30_clients: int = 0


class CollectionExposureService:
    """
    Calcula la exposicion exigible por cliente para las tarjetas de cobranzas.

    El informe de vencimientos (`CollectionDueReportService`) es un listado por
    documento y por eso su importe es el bruto del documento: los pagos
    generales de FEMAG no se imputan a un presupuesto concreto. Este servicio
    aporta la otra mitad: cuanto de esa masa de documentos se puede exigir
    hoy, descontando el saldo real de cada cliente.

    La regla es la misma que ya usa la Cuenta Corriente
    (`ledger_query_service.client_portfolio_rows`): la exposicion de un cliente
    nunca puede superar su saldo.
    """

    def snapshot(
        self,
        *,
        today: date | None = None,
        rows: tuple[dict, ...] | None = None,
        balances: dict[int, Decimal] | None = None,
    ) -> CollectionExposure:
        today = today or date.today()
        if rows is None:
            rows = CollectionDueReportService().report(CollectionDueFilters(), today=today).rows
        if balances is None:
            balances = client_balances_by_id()
        buckets = self._buckets_by_client(rows, today=today)
        return self._exposure(buckets, balances)

    def _buckets_by_client(
        self,
        rows: tuple[dict, ...],
        *,
        today: date,
    ) -> dict[int, dict[str, Decimal]]:
        buckets: dict[int, dict[str, Decimal]] = defaultdict(
            lambda: {
                _BUCKET_OVERDUE: Decimal("0.00"),
                _BUCKET_TODAY: Decimal("0.00"),
                _BUCKET_NEXT_7: Decimal("0.00"),
                _BUCKET_NEXT_30: Decimal("0.00"),
            }
        )
        for row in rows:
            for bucket in self._buckets_for(row["due_date"], today=today):
                buckets[row["client_id"]][bucket] += _money(row["total_amount"])
        return buckets

    def _exposure(
        self,
        buckets: dict[int, dict[str, Decimal]],
        balances: dict[int, Decimal],
    ) -> CollectionExposure:
        totals = {
            _BUCKET_OVERDUE: Decimal("0.00"),
            _BUCKET_TODAY: Decimal("0.00"),
            _BUCKET_NEXT_7: Decimal("0.00"),
            _BUCKET_NEXT_30: Decimal("0.00"),
        }
        clients = {_BUCKET_OVERDUE: 0, _BUCKET_TODAY: 0, _BUCKET_NEXT_7: 0, _BUCKET_NEXT_30: 0}

        for client_id, client_buckets in buckets.items():
            pool = max(balances.get(client_id, Decimal("0.00")), Decimal("0.00"))

            # Lo vencido se cobra primero: es lo que el cliente ya tiene en su
            # cuenta corriente y no puede pagar dos veces.
            overdue = min(client_buckets[_BUCKET_OVERDUE], pool)
            pool -= overdue

            # Lo que vence hoy sigue al vencido.
            due_today = min(client_buckets[_BUCKET_TODAY], pool)
            pool -= due_today

            # Las ventanas de 7 y 30 dias se superponen entre si (la de 30
            # incluye la de 7) y por eso las dos se miden contra el mismo
            # remanente, sin descontarse una de la otra.
            next_7 = min(client_buckets[_BUCKET_NEXT_7], pool)
            next_30 = min(client_buckets[_BUCKET_NEXT_30], pool)

            for bucket, amount in (
                (_BUCKET_OVERDUE, overdue),
                (_BUCKET_TODAY, due_today),
                (_BUCKET_NEXT_7, next_7),
                (_BUCKET_NEXT_30, next_30),
            ):
                totals[bucket] += amount
                if amount > 0:
                    clients[bucket] += 1

        return CollectionExposure(
            overdue_amount=float(totals[_BUCKET_OVERDUE].quantize(_MONEY_QUANTUM)),
            overdue_clients=clients[_BUCKET_OVERDUE],
            due_today_amount=float(totals[_BUCKET_TODAY].quantize(_MONEY_QUANTUM)),
            due_today_clients=clients[_BUCKET_TODAY],
            next_7_amount=float(totals[_BUCKET_NEXT_7].quantize(_MONEY_QUANTUM)),
            next_7_clients=clients[_BUCKET_NEXT_7],
            next_30_amount=float(totals[_BUCKET_NEXT_30].quantize(_MONEY_QUANTUM)),
            next_30_clients=clients[_BUCKET_NEXT_30],
        )

    @staticmethod
    def _buckets_for(due_date: date, *, today: date) -> tuple[str, ...]:
        """
        Ventanas a las que pertenece un documento.

        La ventana de 30 dias es **acumulada** (incluye la de 7), igual que la
        del informe de vencimientos: un documento que vence dentro de 7 dias
        cuenta en las dos.
        """
        days = (due_date - today).days
        if days < 0:
            return (_BUCKET_OVERDUE,)
        if days == 0:
            return (_BUCKET_TODAY,)
        if days <= 7:
            return (_BUCKET_NEXT_7, _BUCKET_NEXT_30)
        if days <= 30:
            return (_BUCKET_NEXT_30,)
        return ()

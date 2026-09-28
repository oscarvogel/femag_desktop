from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.load_orders import LoadOrder, LoadOrderProduct


@dataclass(frozen=True)
class ProfitabilityLine:
    date: date
    order_number: int
    client: str
    product: str
    quantity: float
    unit: str
    sale_unit_price: float
    applied_unit_cost: float | None
    sale_amount: float
    cost_amount: float | None
    gross_profit: float | None
    margin_percent: float | None


@dataclass(frozen=True)
class ProfitabilitySnapshot:
    lines: tuple[ProfitabilityLine, ...]
    sales: float
    known_cost_sales: float
    cost: float
    gross_profit: float
    margin_percent: float | None
    cost_coverage_percent: float


class ProductProfitabilityService:
    EFFECTIVE_STATUSES = (LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_CLOSED)

    def snapshot(self, start: date, end: date) -> ProfitabilitySnapshot:
        query = (
            LoadOrderProduct.select(LoadOrderProduct, LoadOrder)
            .join(LoadOrder)
            .where(
                LoadOrder.status.in_(self.EFFECTIVE_STATUSES),
                LoadOrder.date.between(start, end),
            )
            .order_by(LoadOrder.date.desc(), LoadOrder.order_number.desc(), LoadOrderProduct.id)
        )
        rows = []
        sales = known_sales = cost = profit = 0.0
        for line in query:
            sale = round(float(line.total or 0), 2)
            qty = float(line.quantity or 0)
            unit_price = float(line.precio_neto_unitario or 0)
            client = line.destination.client.name if line.destination_id else (line.order.client.name if line.order.client_id else "-")
            applied = line.costo_unitario_aplicado
            if applied is None:
                line_cost = line_profit = margin = None
            else:
                line_cost = round(qty * float(applied), 2)
                line_profit = round(sale - line_cost, 2)
                margin = round(line_profit / sale * 100, 2) if sale else None
                known_sales += sale
                cost += line_cost
                profit += line_profit
            sales += sale
            rows.append(ProfitabilityLine(
                date=line.order.date, order_number=line.order.order_number, client=client,
                product=line.product.name, quantity=qty, unit=line.unit,
                sale_unit_price=unit_price, applied_unit_cost=float(applied) if applied is not None else None,
                sale_amount=sale, cost_amount=line_cost, gross_profit=line_profit, margin_percent=margin,
            ))
        return ProfitabilitySnapshot(
            lines=tuple(rows), sales=round(sales, 2), known_cost_sales=round(known_sales, 2),
            cost=round(cost, 2), gross_profit=round(profit, 2),
            margin_percent=round(profit / known_sales * 100, 2) if known_sales else None,
            cost_coverage_percent=round(known_sales / sales * 100, 2) if sales else 100.0,
        )

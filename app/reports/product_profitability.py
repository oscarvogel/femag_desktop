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
class ProductProfitabilitySummary:
    product: str
    quantity: float
    unit: str
    sales: float
    known_cost_sales: float
    cost: float
    gross_profit: float
    margin_percent: float | None
    cost_coverage_percent: float


@dataclass(frozen=True)
class ProfitabilitySnapshot:
    lines: tuple[ProfitabilityLine, ...]
    products: tuple[ProductProfitabilitySummary, ...]
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
            # Rentabilidad compara costo contra venta neta gravada, sin IVA.
            # El total incluye IVA y sobreestimaria utilidad y margen.
            sale = round(float(line.neto_gravado or 0), 2)
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
        grouped = {}
        for row in rows:
            key = (row.product, row.unit)
            item = grouped.setdefault(key, {
                "quantity": 0.0, "sales": 0.0, "known_sales": 0.0,
                "cost": 0.0, "profit": 0.0,
            })
            item["quantity"] += row.quantity
            item["sales"] += row.sale_amount
            if row.cost_amount is not None:
                item["known_sales"] += row.sale_amount
                item["cost"] += row.cost_amount
                item["profit"] += row.gross_profit or 0.0
        products = []
        for (product, unit), item in grouped.items():
            known = item["known_sales"]
            total_sales = item["sales"]
            products.append(ProductProfitabilitySummary(
                product=product, quantity=round(item["quantity"], 4), unit=unit,
                sales=round(total_sales, 2), known_cost_sales=round(known, 2),
                cost=round(item["cost"], 2), gross_profit=round(item["profit"], 2),
                margin_percent=round(item["profit"] / known * 100, 2) if known else None,
                cost_coverage_percent=round(known / total_sales * 100, 2) if total_sales else 100.0,
            ))
        products.sort(key=lambda item: item.sales, reverse=True)
        return ProfitabilitySnapshot(
            lines=tuple(rows), products=tuple(products), sales=round(sales, 2), known_cost_sales=round(known_sales, 2),
            cost=round(cost, 2), gross_profit=round(profit, 2),
            margin_percent=round(profit / known_sales * 100, 2) if known_sales else None,
            cost_coverage_percent=round(known_sales / sales * 100, 2) if sales else 100.0,
        )

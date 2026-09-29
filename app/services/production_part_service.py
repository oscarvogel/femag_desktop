from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.production import ProductionPart


@dataclass(frozen=True)
class ProductionTotals:
    parts: int
    cassava_processed_kg: Decimal
    starch_produced_kg: Decimal
    real_yield: Decimal


class ProductionPartService:
    @staticmethod
    def _values(*, shift: str, cassava_processed_kg, starch_produced_kg, observations: str = ""):
        shift = (shift or "").strip()
        processed = Decimal(str(cassava_processed_kg))
        produced = Decimal(str(starch_produced_kg))
        if not shift:
            raise ValueError("El turno es obligatorio.")
        if processed <= 0:
            raise ValueError("Los kg de mandioca procesados deben ser mayores a cero.")
        if produced < 0:
            raise ValueError("Los kg de fécula producidos no pueden ser negativos.")
        return shift, processed, produced, (observations or "").strip() or None

    @classmethod
    def create(cls, *, production_date: date, shift: str, cassava_processed_kg, starch_produced_kg, observations: str = "") -> ProductionPart:
        shift, processed, produced, observations = cls._values(
            shift=shift, cassava_processed_kg=cassava_processed_kg,
            starch_produced_kg=starch_produced_kg, observations=observations,
        )
        return ProductionPart.create(
            production_date=production_date, shift=shift,
            cassava_processed_kg=processed, starch_produced_kg=produced,
            observations=observations,
        )

    @classmethod
    def update(cls, part: ProductionPart, *, production_date: date, shift: str, cassava_processed_kg, starch_produced_kg, observations: str = "") -> ProductionPart:
        shift, processed, produced, observations = cls._values(
            shift=shift, cassava_processed_kg=cassava_processed_kg,
            starch_produced_kg=starch_produced_kg, observations=observations,
        )
        part.production_date = production_date
        part.shift = shift
        part.cassava_processed_kg = processed
        part.starch_produced_kg = produced
        part.observations = observations
        part.save()
        return part

    @staticmethod
    def annul(part: ProductionPart) -> None:
        part.delete_instance()

    @staticmethod
    def for_day(day: date):
        return list(
            ProductionPart.select()
            .where(ProductionPart.production_date == day)
            .order_by(ProductionPart.id)
        )

    @staticmethod
    def totals(rows) -> ProductionTotals:
        rows = list(rows)
        processed = sum((Decimal(str(row.cassava_processed_kg)) for row in rows), Decimal("0"))
        produced = sum((Decimal(str(row.starch_produced_kg)) for row in rows), Decimal("0"))
        real_yield = (
            (produced * Decimal("100") / processed).quantize(Decimal("0.01"))
            if processed > 0 else Decimal("0.00")
        )
        return ProductionTotals(len(rows), processed, produced, real_yield)

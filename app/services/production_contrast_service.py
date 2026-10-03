from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.models.production import ProductionBag, ProductionPart, RawMaterialReceipt

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ONE_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class ProductionContrast:
    """Contraste entre lo que la planta recibio y lo que produjo de verdad.

    Ojo con ``processed_kg``: el sistema **no** registra cuantas kilos de
    mandioca entraron al proceso, solo cuantos entraron al deposito. Por eso
    aca se asume que toda la mandioca recibida se proceso el mismo dia. Esa
    assumption es lo que hay que revisar con el dueÃ±o: si queda producto
    terminado del dia anterior (WIP o arranque), el rinde real sale mal porque
    el numerador y el denominador son de dias distintos.
    """

    day: date
    received_tickets: int
    received_kg: Decimal
    theoretical_yield_pct: Decimal
    theoretical_starch_kg: Decimal
    real_starch_kg: Decimal
    real_bags: int
    real_parts: int
    pending_parts: int

    @property
    def processed_kg(self) -> Decimal:
        """Mandioca que se asume procesada. Hoy: lo recibido."""
        return self.received_kg

    @property
    def real_yield_pct(self) -> Decimal | None:
        if self.processed_kg <= ZERO:
            return None
        return (self.real_starch_kg / self.processed_kg * ONE_HUNDRED).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def deviation_kg(self) -> Decimal | None:
        """Kg de mas (o de menos) respecto de la teoria. Positivo es mejor rinde.

        Sin teoria no hay contra que comparar, asi que se devuelve None en vez
        de mostrar el total como si fuera un desvio de 100 %.
        """
        if self.theoretical_starch_kg <= ZERO:
            return None
        return self.real_starch_kg - self.theoretical_starch_kg

    @property
    def deviation_pct(self) -> Decimal | None:
        deviation = self.deviation_kg
        if deviation is None:
            return None
        return (deviation / self.theoretical_starch_kg * ONE_HUNDRED).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def has_receipts(self) -> bool:
        return self.received_kg > ZERO

    @property
    def has_confirmed_production(self) -> bool:
        return self.real_parts > 0


class ProductionContrastService:
    """Solo lectura: no escribe nada. Compara recepciones contra partes confirmados."""

    @staticmethod
    def receipts_of(day: date) -> list[RawMaterialReceipt]:
        return list(
            RawMaterialReceipt.select()
            .where(
                (RawMaterialReceipt.received_at >= datetime.combine(day, time.min))
                & (RawMaterialReceipt.received_at < datetime.combine(day, time.min) + timedelta(days=1))
            )
            .order_by(RawMaterialReceipt.received_at, RawMaterialReceipt.source_comp)
        )

    @staticmethod
    def parts_of(day: date) -> list[ProductionPart]:
        return list(
            ProductionPart.select()
            .where(ProductionPart.production_date == day)
            .order_by(ProductionPart.id)
        )

    @classmethod
    def for_day(cls, day: date) -> ProductionContrast:
        receipts = cls.receipts_of(day)
        parts = cls.parts_of(day)

        received_kg = ZERO
        weighted_sum = ZERO
        theoretical_starch_kg = ZERO
        for receipt in receipts:
            payable = Decimal(str(receipt.payable_kg or 0))
            rendes = Decimal(str(receipt.yield_average or 0))
            received_kg += payable
            # El rinde teorico se pondera por kilos liquidados, que es como se
            # pesa una planta: no todos los tickets pesan lo mismo.
            weighted_sum += payable * rendes
            theoretical_starch_kg += Decimal(str(receipt.theoretical_starch_kg or 0))

        real_starch_kg = ZERO
        real_bags = 0
        real_parts = 0
        pending_parts = 0
        for part in parts:
            if part.is_voided:
                continue
            if not part.is_confirmed:
                # Un borrador todavia se puede cambiar: no cuenta como real.
                pending_parts += 1
                continue
            real_parts += 1
            for bag in part.bags:
                real_starch_kg += Decimal(str(bag.kg or 0))
                real_bags += int(bag.bags or 0)

        theoretical_yield_pct = (
            (weighted_sum / received_kg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if received_kg > ZERO
            else ZERO
        )

        return ProductionContrast(
            day=day,
            received_tickets=len(receipts),
            received_kg=received_kg,
            theoretical_yield_pct=theoretical_yield_pct,
            theoretical_starch_kg=theoretical_starch_kg.quantize(CENT),
            real_starch_kg=real_starch_kg.quantize(CENT),
            real_bags=real_bags,
            real_parts=real_parts,
            pending_parts=pending_parts,
        )

    @staticmethod
    def receipt_lines(day: date) -> list[tuple]:
        return [
            (
                (r.supplier_name or "").strip() or r.supplier_code,
                (r.product_name or "").strip() or r.product_code,
                Decimal(str(r.payable_kg or 0)),
                Decimal(str(r.yield_average or 0)),
                Decimal(str(r.theoretical_starch_kg or 0)),
            )
            for r in ProductionContrastService.receipts_of(day)
        ]

    @staticmethod
    def part_lines(day: date) -> list[tuple]:
        filas = []
        for part in ProductionContrastService.parts_of(day):
            if part.is_voided:
                continue
            for bag in part.bags:
                filas.append(
                    (
                        part.shift,
                        part.status_label,
                        bag.product.name,
                        int(bag.bags or 0),
                        Decimal(str(bag.kg or 0)),
                    )
                )
        return filas

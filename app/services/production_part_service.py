from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.models.production import ProductionBag, ProductionPart

TWO_PLACES = Decimal("0.01")
THREE_PLACES = Decimal("0.001")


@dataclass(frozen=True)
class ProductionTotals:
    parts: int
    lines: int
    bags: int
    kg: Decimal


class ProductionPartService:
    """Registro de produccion real por bolsas embolsadas (#580).

    En planta no se pueden medir los kg de mandioca procesada ni los kg de
    fecula producida por turno, asi que el parte carga cuantas bolsas de cada
    producto se embolsaron y deriva los kg del peso del producto.
    """

    @staticmethod
    def _unit_weight(product) -> Decimal:
        try:
            weight = Decimal(str(product.peso_unitario_kg or 0))
        except InvalidOperation:
            weight = Decimal("0")
        if weight <= 0:
            raise ValueError(
                f"El producto '{product.name}' no tiene peso unitario cargado. "
                "Cargalo en el maestro de productos antes de registrar bolsas: "
                "sin ese peso no se pueden calcular los kg."
            )
        return weight.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)

    @classmethod
    def _lines(cls, lines) -> list[tuple]:
        lines = list(lines or [])
        if not lines:
            raise ValueError("Cargá al menos un producto embolsado en el turno.")
        prepared = []
        seen: set[int] = set()
        for product, raw_bags in lines:
            if product is None:
                raise ValueError("Cada línea necesita un producto.")
            if product.id in seen:
                raise ValueError(
                    f"El producto '{product.name}' está cargado dos veces en el mismo turno."
                )
            seen.add(product.id)
            try:
                bags = Decimal(str(raw_bags))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser un número entero."
                ) from None
            if bags != bags.to_integral_value():
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser un número entero."
                )
            if bags <= 0:
                raise ValueError(
                    f"La cantidad de bolsas de '{product.name}' debe ser mayor a cero."
                )
            weight = cls._unit_weight(product)
            kg = (weight * bags).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            prepared.append((product, int(bags), weight, kg))
        return prepared

    @staticmethod
    def _values(*, shift: str, observations: str = ""):
        shift = (shift or "").strip()
        if not shift:
            raise ValueError("El turno es obligatorio.")
        return shift, (observations or "").strip() or None

    @classmethod
    def create(
        cls, *, production_date: date, shift: str, lines, observations: str = ""
    ) -> ProductionPart:
        shift, observations = cls._values(shift=shift, observations=observations)
        prepared = cls._lines(lines)
        with ProductionPart._meta.database.atomic():
            part = ProductionPart.create(
                production_date=production_date, shift=shift, observations=observations
            )
            cls._write_lines(part, prepared)
        return part

    @classmethod
    def update(
        cls, part: ProductionPart, *, production_date: date, shift: str, lines,
        observations: str = "",
    ) -> ProductionPart:
        shift, observations = cls._values(shift=shift, observations=observations)
        prepared = cls._lines(lines)
        with ProductionPart._meta.database.atomic():
            part.production_date = production_date
            part.shift = shift
            part.observations = observations
            part.save()
            cls._delete_lines(part)
            cls._write_lines(part, prepared)
        return part

    @staticmethod
    def _write_lines(part: ProductionPart, prepared: list[tuple]) -> None:
        for product, bags, weight, kg in prepared:
            ProductionBag.create(
                part=part, product=product, bags=bags, unit_weight_kg=weight, kg=kg
            )

    @staticmethod
    def annul(part: ProductionPart) -> None:
        ProductionPartService._delete_lines(part)
        part.delete_instance()

    @staticmethod
    def for_day(day: date):
        return list(
            ProductionPart.select()
            .where(ProductionPart.production_date == day)
            .order_by(ProductionPart.id)
            .prefetch(ProductionBag)
        )

    @staticmethod
    def lines_of(part: ProductionPart):
        """Lineas del parte, tolerando que ``part.bags`` venga prefetcheado."""
        bags = part.bags
        if isinstance(bags, (list, tuple)):
            return sorted(bags, key=lambda bag: bag.id)
        return list(bags.order_by(ProductionBag.id))

    @staticmethod
    def _delete_lines(part: ProductionPart) -> None:
        ProductionBag.delete().where(ProductionBag.part == part).execute()

    @staticmethod
    def totals(rows) -> ProductionTotals:
        rows = list(rows)
        lines = 0
        bags = 0
        kg = Decimal("0")
        for row in rows:
            for bag in ProductionPartService.lines_of(row):
                lines += 1
                bags += int(bag.bags or 0)
                kg += Decimal(str(bag.kg or 0))
        return ProductionTotals(len(rows), lines, bags, kg)

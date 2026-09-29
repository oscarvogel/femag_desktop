from datetime import date
from decimal import Decimal

import pytest

from app.models.production import ProductionPart
from app.services.production_part_service import ProductionPartService


def test_production_part_calculates_real_yield(db):
    row = ProductionPart.create(
        production_date=date(2026, 9, 29), shift="Mañana",
        cassava_processed_kg=Decimal("32000"), starch_produced_kg=Decimal("7050"),
    )
    assert row.real_yield == Decimal("22.03")


def test_production_totals_use_actual_processed_and_produced(db):
    ProductionPart.create(production_date=date(2026, 9, 29), shift="Mañana", cassava_processed_kg=32000, starch_produced_kg=7050)
    ProductionPart.create(production_date=date(2026, 9, 29), shift="Tarde", cassava_processed_kg=33000, starch_produced_kg=7180)
    totals = ProductionPartService.totals(ProductionPartService.for_day(date(2026, 9, 29)))
    assert totals.parts == 2
    assert totals.cassava_processed_kg == Decimal("65000")
    assert totals.starch_produced_kg == Decimal("14230")
    assert totals.real_yield == Decimal("21.89")


def test_production_part_requires_positive_processed_kilos(db):
    with pytest.raises(ValueError, match="mayores a cero"):
        ProductionPartService.create(
            production_date=date(2026, 9, 29), shift="Mañana",
            cassava_processed_kg=0, starch_produced_kg=100,
        )

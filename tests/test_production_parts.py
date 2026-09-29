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


def test_production_part_can_be_corrected_and_annulled(db):
    row = ProductionPartService.create(
        production_date=date(2026, 9, 29), shift="Mañana",
        cassava_processed_kg=25000, starch_produced_kg=5232,
    )
    row = ProductionPartService.update(
        row, production_date=date(2026, 9, 29), shift="Mañana",
        cassava_processed_kg=23000, starch_produced_kg=5000,
        observations="Corrección de carga",
    )
    assert row.cassava_processed_kg == Decimal("23000")
    assert row.starch_produced_kg == Decimal("5000")
    assert row.real_yield == Decimal("21.74")
    assert row.observations == "Corrección de carga"

    ProductionPartService.annul(row)
    assert ProductionPart.select().count() == 0


def test_for_day_keeps_dates_independent(db):
    ProductionPartService.create(
        production_date=date(2026, 9, 28), shift="Mañana",
        cassava_processed_kg=25000, starch_produced_kg=5232,
    )
    ProductionPartService.create(
        production_date=date(2026, 9, 29), shift="Mañana",
        cassava_processed_kg=30000, starch_produced_kg=6300,
    )
    rows = ProductionPartService.for_day(date(2026, 9, 28))
    assert len(rows) == 1
    assert rows[0].production_date == date(2026, 9, 28)

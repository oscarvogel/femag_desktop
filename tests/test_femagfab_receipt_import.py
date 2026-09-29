from datetime import datetime
from decimal import Decimal

from app.importers.femagfab import LegacyReceipt
from app.services.raw_material_receipt_import_service import RawMaterialReceiptImportService


def receipt(payable="10000", yield_average="25.00", legacy="0"):
    return LegacyReceipt(
        comp="123", received_at=datetime(2026, 9, 29, 10, 0),
        supplier_code="0001", supplier_name="Proveedor", product_code="01",
        product_name="Mandioca", gross_kg=Decimal("20000"), tare_kg=Decimal("10000"),
        net_kg=Decimal("10000"), payable_kg=Decimal(payable),
        earth_discount_pct=Decimal("0"), cepa_discount_pct=Decimal("0"),
        yield_1=Decimal("25"), yield_2=Decimal("25"), yield_3=Decimal("25"),
        yield_average=Decimal(yield_average), legacy_starch_kg=Decimal(legacy),
    )


def test_theoretical_starch_does_not_trust_legacy_fecula():
    row = receipt(legacy="0")
    assert row.theoretical_starch_kg == Decimal("2500.00")


def test_hash_changes_when_productive_source_changes():
    before = receipt(yield_average="25.00")
    after = receipt(yield_average="24.50")
    assert before.source_hash != after.source_hash


def test_weighted_yield_uses_payable_kilos():
    rows = [receipt(payable="10000", yield_average="20"), receipt(payable="30000", yield_average="30")]
    totals = RawMaterialReceiptImportService.totals(rows)
    assert totals.tickets == 2
    assert totals.payable_kg == Decimal("40000")
    assert totals.theoretical_starch_kg == Decimal("11000.00")
    assert totals.weighted_yield == Decimal("27.5")

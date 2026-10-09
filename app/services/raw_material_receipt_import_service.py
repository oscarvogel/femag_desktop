from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.importers.femagfab import FemagFabSource, LegacyReceipt
from app.models.production import RawMaterialReceipt


@dataclass(frozen=True)
class ReceiptPreview:
    row: LegacyReceipt
    source_key: str
    status: str


@dataclass(frozen=True)
class ReceiptTotals:
    tickets: int
    payable_kg: Decimal
    theoretical_starch_kg: Decimal
    weighted_yield: Decimal


class RawMaterialReceiptImportService:
    NEW = "nuevo"
    UNCHANGED = "sin_cambios"
    MODIFIED = "modificado"

    def __init__(self, source: FemagFabSource | None = None):
        self.source = source or FemagFabSource()

    def preview(self, day: date) -> tuple[list[ReceiptPreview], ReceiptTotals]:
        rows = self.source.fetch_day(day)
        previews = []
        for row in rows:
            key = self.source.source_key(row.comp)
            existing = RawMaterialReceipt.get_or_none(RawMaterialReceipt.source_key == key)
            if existing is None:
                status = self.NEW
            elif existing.source_hash == row.source_hash:
                status = self.UNCHANGED
            else:
                status = self.MODIFIED
            previews.append(ReceiptPreview(row=row, source_key=key, status=status))
        return previews, self.totals(rows)

    @staticmethod
    def totals(rows: list[LegacyReceipt]) -> ReceiptTotals:
        payable = sum((row.payable_kg for row in rows), Decimal("0"))
        starch = sum((row.theoretical_starch_kg for row in rows), Decimal("0"))
        weighted = (
            sum((row.payable_kg * row.yield_average for row in rows), Decimal("0")) / payable
            if payable else Decimal("0")
        )
        return ReceiptTotals(len(rows), payable, starch, weighted)

    def import_new(self, previews: list[ReceiptPreview]) -> int:
        created = 0
        for preview in previews:
            if preview.status != self.NEW:
                continue
            row = preview.row
            RawMaterialReceipt.create(
                source_key=preview.source_key, source_instance=self.source.instance,
                source_comp=row.comp, source_hash=row.source_hash,
                received_at=row.received_at, supplier_code=row.supplier_code,
                supplier_name=row.supplier_name or None, product_code=row.product_code,
                product_name=row.product_name or None, gross_kg=row.gross_kg,
                tare_kg=row.tare_kg, net_kg=row.net_kg, payable_kg=row.payable_kg,
                earth_discount_pct=row.earth_discount_pct, cepa_discount_pct=row.cepa_discount_pct,
                yield_1=row.yield_1, yield_2=row.yield_2, yield_3=row.yield_3,
                yield_average=row.yield_average, legacy_starch_kg=row.legacy_starch_kg,
                theoretical_starch_kg=row.theoretical_starch_kg,
                source_payload=__import__("json").dumps(row.payload(), ensure_ascii=False, sort_keys=True),
            )
            created += 1
        return created

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from app.importers.femagfab import FemagFabSource, LegacyReceipt
from app.models.production import RawMaterialReceipt


ProgressCallback = Callable[[str, int, int], None]


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
        return self.preview_range(day, day)

    def preview_range(
        self,
        start_day: date,
        end_day: date,
        progress: ProgressCallback | None = None,
    ) -> tuple[list[ReceiptPreview], ReceiptTotals]:
        """Previsualiza un rango inclusivo, informando avance de a un ticket."""
        if progress:
            progress("consulta", 0, 0)
        rows = self.source.fetch_range(start_day, end_day)
        keys = [self.source.source_key(row.comp) for row in rows]
        existing = self._existing_hashes(keys)
        total = len(rows)
        if progress:
            progress("revision", 0, total)
        previews = []
        for index, (row, key) in enumerate(zip(rows, keys), start=1):
            current_hash = existing.get(key)
            if current_hash is None:
                status = self.NEW
            elif current_hash == row.source_hash:
                status = self.UNCHANGED
            else:
                status = self.MODIFIED
            previews.append(ReceiptPreview(row=row, source_key=key, status=status))
            if progress:
                progress("revision", index, total)
        return previews, self.totals(rows)

    @staticmethod
    def _existing_hashes(keys: list[str]) -> dict[str, str]:
        """Resuelve todos los source_key del rango en pocas consultas."""
        hashes: dict[str, str] = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            query = RawMaterialReceipt.select(
                RawMaterialReceipt.source_key, RawMaterialReceipt.source_hash
            ).where(RawMaterialReceipt.source_key.in_(chunk))
            for record in query:
                hashes[record.source_key] = record.source_hash
        return hashes

    @staticmethod
    def totals(rows: list[LegacyReceipt]) -> ReceiptTotals:
        payable = sum((row.payable_kg for row in rows), Decimal("0"))
        starch = sum((row.theoretical_starch_kg for row in rows), Decimal("0"))
        weighted = (
            sum((row.payable_kg * row.yield_average for row in rows), Decimal("0")) / payable
            if payable else Decimal("0")
        )
        return ReceiptTotals(len(rows), payable, starch, weighted)

    def import_new(
        self,
        previews: list[ReceiptPreview],
        progress: ProgressCallback | None = None,
    ) -> int:
        pending = [preview for preview in previews if preview.status == self.NEW]
        total = len(pending)
        created = 0
        for index, preview in enumerate(pending, start=1):
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
            if progress:
                progress("importacion", index, total)
        return created

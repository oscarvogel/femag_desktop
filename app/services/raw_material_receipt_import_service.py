from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Callable

from app.importers.femagfab import FemagFabSource, LegacyReceipt
from app.models.production import (
    RawMaterialReceipt, YIELD_SOURCE_ESTIMATED, YIELD_SOURCE_MEASURED,
)
from app.services.estimated_yield_service import EstimatedYieldService


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
    # Desglose por origen del rinde (#722). El rendimiento ponderado sale solo
    # de los tickets medidos: mezclar los estimados ahi haria que el numero
    # del mes pareciera peor de lo que es.
    measured_tickets: int
    measured_payable_kg: Decimal
    estimated_tickets: int
    estimated_payable_kg: Decimal
    estimated_starch_kg: Decimal
    # Rinde que se aplico a los tickets estimados de esta consulta.
    estimated_yield_pct: Decimal


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
        rows = [self._with_effective_yield(row) for row in rows]
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
    def _with_effective_yield(row: LegacyReceipt) -> LegacyReceipt:
        """Aplica el rinde estimado a las cargas que llegaron sin rinde (#722).

        El ticket conserva su PROMEDIO de origen (0) y delega el valor aplicado
        en ``applied_yield_pct``. Como el hash se calcula sobre el contenido
        de origen, cambiar el parametro despues no invalida lo ya importado.
        """
        if not row.is_estimated_yield:
            return row
        return replace(
            row, applied_yield_pct=EstimatedYieldService.estimated_yield_pct()
        )

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
        measured = [row for row in rows if not row.is_estimated_yield]
        estimated = [row for row in rows if row.is_estimated_yield]
        measured_payable = sum((row.payable_kg for row in measured), Decimal("0"))
        # El rendimiento ponderado se calcula solo con los tickets medidos: si
        # entraran los estimados, un ticket sin rinde (0 %) hundiria el promedio
        # del rango (#722).
        weighted = (
            sum((row.payable_kg * row.yield_average for row in measured), Decimal("0"))
            / measured_payable
            if measured_payable else Decimal("0")
        )
        return ReceiptTotals(
            tickets=len(rows),
            payable_kg=payable,
            theoretical_starch_kg=starch,
            weighted_yield=weighted,
            measured_tickets=len(measured),
            measured_payable_kg=measured_payable,
            estimated_tickets=len(estimated),
            estimated_payable_kg=sum((row.payable_kg for row in estimated), Decimal("0")),
            estimated_starch_kg=sum((row.theoretical_starch_kg for row in estimated), Decimal("0")),
            estimated_yield_pct=next(
                (
                    row.applied_yield_pct
                    for row in estimated
                    if row.applied_yield_pct is not None
                ),
                Decimal("0.00"),
            ),
        )

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
                yield_source=(
                    YIELD_SOURCE_ESTIMATED if row.is_estimated_yield else YIELD_SOURCE_MEASURED
                ),
                estimated_yield_pct=(
                    row.applied_yield_pct if row.is_estimated_yield else None
                ),
                source_payload=__import__("json").dumps(row.payload(), ensure_ascii=False, sort_keys=True),
            )
            created += 1
            if progress:
                progress("importacion", index, total)
        return created

"""Importacion del maestro de proveedores/colonos desde `femagfab.proveedo` (#938).

El legacy no tiene personas: tiene codigos de cuatro caracteres con nombres
repetidos. Este servicio arma el maestro de FEMAG Desktop, donde **una persona
es un registro**, y deja la ficha original del legacy aparte para poder
auditar cada unificacion.

La deduplicacion es por nombre normalizado. Es una heuristica, no una
certidumbre: por eso la persona queda con ``identity_verified = False`` y con
la lista de codigos legacy que la originan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata

from app.importers.femagfab import FemagFabSource, LegacySupplier
from app.models.suppliers import Supplier, SupplierLegacyCode


@dataclass(frozen=True)
class SkippedSupplier:
    """Ficha del legacy que no se importo, con el motivo."""

    code: str
    name: str
    reason: str


@dataclass
class SupplierImportReport:
    """Resultado de una importacion del maestro de proveedores."""

    created: int = 0
    updated: int = 0
    merged: int = 0
    unchanged: int = 0
    skipped: list[SkippedSupplier] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.merged + self.unchanged

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def summary(self) -> str:
        return (
            f"{self.created} creados, {self.merged} unificados, "
            f"{self.updated} actualizados, {self.unchanged} sin cambios, "
            f"{self.skipped_count} descartados"
        )


def normalize_supplier_name(name: str) -> str:
    """Normaliza un nombre para comparar personas.

    Sin tildes, sin mayusculas y con espacios colapsados: asi "NUNEZ JULIO" y
    "Nuñez  Julio " son la misma persona para el legacy, que solo distingue por
    el codigo de cuatro caracteres.
    """
    text = " ".join((name or "").split())
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.upper()


class SupplierImportService:
    """Importa el maestro de proveedores desde `femagfab.proveedo`."""

    SKIPPED_PLACEHOLDER = "placeholder"
    SKIPPED_EMPTY_NAME = "sin_nombre"

    def __init__(self, source: FemagFabSource | None = None):
        self.source = source or FemagFabSource()

    def import_suppliers(self) -> SupplierImportReport:
        """Importa el maestro completo. Es idempotente: se puede repetir."""
        report = SupplierImportReport()
        rows = self.source.fetch_suppliers()
        for row in rows:
            self._import_one(row, report)
        return report

    def _import_one(self, row: LegacySupplier, report: SupplierImportReport) -> None:
        if row.is_placeholder:
            report.skipped.append(
                SkippedSupplier(
                    code=row.code, name=row.name, reason=self.SKIPPED_PLACEHOLDER
                )
            )
            return
        normalized = normalize_supplier_name(row.name)
        if not normalized:
            report.skipped.append(
                SkippedSupplier(
                    code=row.code, name=row.name, reason=self.SKIPPED_EMPTY_NAME
                )
            )
            return
        source_key = self.source.supplier_source_key(row.code)
        ficha = SupplierLegacyCode.get_or_none(
            SupplierLegacyCode.source_key == source_key
        )
        if ficha is not None:
            self._update_existing(ficha, row, normalized, report)
            return

        supplier = Supplier.get_or_none(
            Supplier.normalized_name == normalized
        )
        if supplier is None:
            supplier = Supplier.create(
                name=row.name,
                normalized_name=normalized,
                locality=row.locality or None,
                phone=row.phone or None,
                identity_verified=False,
            )
            report.created += 1
        else:
            # Misma persona con otro codigo del legacy: se unifica.
            report.merged += 1
        SupplierLegacyCode.create(
            supplier=supplier,
            source_instance=self.source.instance,
            code=row.code,
            source_key=source_key,
            name=row.name,
            locality=row.locality or None,
            phone=row.phone or None,
        )

    def _update_existing(
        self,
        ficha: SupplierLegacyCode,
        row: LegacySupplier,
        normalized: str,
        report: SupplierImportReport,
    ) -> None:
        """Actualiza una ficha ya importada sin romper los documentos."""
        supplier = ficha.supplier
        changed = False
        if ficha.name != row.name:
            ficha.name = row.name
            changed = True
        if (ficha.locality or "") != row.locality:
            ficha.locality = row.locality or None
            changed = True
        if (ficha.phone or "") != row.phone:
            ficha.phone = row.phone or None
            changed = True
        if changed:
            ficha.save()
            report.updated += 1
        else:
            report.unchanged += 1

        # Si el nombre normalizado cambio, la persona puede haberse fusionado
        # con otra ficha. Se recalcula la busqueda por nombre normalizado para
        # no dejar dos personas con el mismo nombre normalizado.
        if supplier.normalized_name != normalized:
            other = Supplier.get_or_none(
                (Supplier.normalized_name == normalized)
                & (Supplier.id != supplier.id)
            )
            if other is not None:
                self._merge(supplier, other, ficha)
                report.merged += 1
                report.updated = max(report.updated - 1, 0)
                return
            supplier.normalized_name = normalized
            supplier.save()
            report.updated += 1

    @staticmethod
    def _merge(survivor: Supplier, absorbed: Supplier, ficha: SupplierLegacyCode) -> None:
        """Fusiona dos personas en una sola, conservando las dos fichas."""
        for otra in list(absorbed.legacy_code_rows):
            otra.supplier = survivor
            otra.save()
        absorbed.delete_instance(recursive=True)
        ficha.supplier = survivor
        ficha.save()

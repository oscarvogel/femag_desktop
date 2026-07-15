from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


QUANTUM = Decimal("0.001")


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(QUANTUM)


def _quantity_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


@dataclass(frozen=True)
class RequestedLine:
    destination_id: int
    product_id: int
    quantity: Decimal
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _decimal(self.quantity))


@dataclass(frozen=True)
class AllocationDraft:
    destination_id: int
    product_id: int
    quantity: Decimal
    peso_unitario_kg: Decimal
    label: str = ""
    client_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        object.__setattr__(self, "peso_unitario_kg", _decimal(self.peso_unitario_kg))

    @property
    def kilos(self) -> Decimal:
        return _decimal(self.quantity * self.peso_unitario_kg)


@dataclass(frozen=True)
class PalletDraft:
    sequence: int
    allocations: tuple[AllocationDraft, ...]


@dataclass(frozen=True)
class CompositionIssue:
    code: str
    message: str
    destination_id: int | None = None
    product_id: int | None = None
    quantity: Decimal = Decimal("0.000")


@dataclass(frozen=True)
class PalletResult:
    sequence: int
    total_kg: Decimal
    allocation_count: int
    client_count: int


@dataclass(frozen=True)
class CompositionResult:
    pallets: tuple[PalletResult, ...]
    issues: tuple[CompositionIssue, ...]
    total_kg: Decimal
    pending_quantity: Decimal

    @property
    def is_complete(self) -> bool:
        return not any(issue.code in {"no_pallets", "pending", "excess"} for issue in self.issues)

    @property
    def can_issue(self) -> bool:
        return bool(self.pallets) and not self.issues


class PalletCompositionService:
    def reconcile(
        self,
        *,
        requested: Iterable[RequestedLine],
        pallets: Iterable[PalletDraft],
    ) -> CompositionResult:
        requested = tuple(requested)
        pallets = tuple(sorted(pallets, key=lambda pallet: pallet.sequence))
        requested_by_key: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0.000"))
        labels: dict[tuple[int, int], str] = {}
        for line in requested:
            key = (line.destination_id, line.product_id)
            requested_by_key[key] = _decimal(requested_by_key[key] + line.quantity)
            labels[key] = line.label

        assigned_by_key: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0.000"))
        pallet_results: list[PalletResult] = []
        zero_weight_keys: set[tuple[int, int]] = set()
        for pallet in pallets:
            total_kg = Decimal("0.000")
            client_ids: set[int] = set()
            for allocation in pallet.allocations:
                key = (allocation.destination_id, allocation.product_id)
                assigned_by_key[key] = _decimal(assigned_by_key[key] + allocation.quantity)
                labels.setdefault(key, allocation.label)
                client_ids.add(allocation.client_id or allocation.destination_id)
                total_kg = _decimal(total_kg + allocation.kilos)
                if allocation.quantity > 0 and allocation.peso_unitario_kg <= 0:
                    zero_weight_keys.add(key)
            pallet_results.append(
                PalletResult(
                    sequence=pallet.sequence,
                    total_kg=total_kg,
                    allocation_count=len(pallet.allocations),
                    client_count=len(client_ids),
                )
            )

        issues: list[CompositionIssue] = []
        if not pallets:
            issues.append(CompositionIssue("no_pallets", "La orden no tiene pallets."))

        pending_quantity = Decimal("0.000")
        for key in sorted(set(requested_by_key) | set(assigned_by_key)):
            requested_quantity = requested_by_key[key]
            assigned_quantity = assigned_by_key[key]
            difference = _decimal(requested_quantity - assigned_quantity)
            label = labels.get(key) or f"Destino {key[0]} / Articulo {key[1]}"
            if difference > 0:
                pending_quantity = _decimal(pending_quantity + difference)
                issues.append(
                    CompositionIssue(
                        "pending",
                        f"{label}: faltan asignar {_quantity_text(difference)} unidades.",
                        key[0],
                        key[1],
                        difference,
                    )
                )
            elif difference < 0:
                excess = -difference
                issues.append(
                    CompositionIssue(
                        "excess",
                        f"{label}: se excede lo solicitado en {_quantity_text(excess)} unidades.",
                        key[0],
                        key[1],
                        excess,
                    )
                )

        for key in sorted(zero_weight_keys):
            label = labels.get(key) or f"Destino {key[0]} / Articulo {key[1]}"
            issues.append(
                CompositionIssue(
                    "zero_weight",
                    f"{label}: el articulo tiene peso pendiente (0 kg).",
                    key[0],
                    key[1],
                )
            )

        total_kg = sum((pallet.total_kg for pallet in pallet_results), Decimal("0.000"))
        return CompositionResult(
            pallets=tuple(pallet_results),
            issues=tuple(issues),
            total_kg=_decimal(total_kg),
            pending_quantity=pending_quantity,
        )

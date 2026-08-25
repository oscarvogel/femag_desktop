from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Iterable


QUANTUM = Decimal("0.001")


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(QUANTUM)


@dataclass(frozen=True)
class DistributionLine:
    destination_id: int
    client_id: int
    product_id: int
    quantity: Decimal
    unit_kg: Decimal
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        object.__setattr__(self, "unit_kg", _decimal(self.unit_kg))
        if self.quantity < 0:
            raise ValueError("La cantidad no puede ser negativa.")
        if self.quantity > 0 and self.unit_kg <= 0:
            raise ValueError("El peso unitario debe ser mayor a cero para distribuir automaticamente.")

    @property
    def kilos(self) -> Decimal:
        return _decimal(self.quantity * self.unit_kg)


@dataclass(frozen=True)
class DistributionAllocation:
    destination_id: int
    client_id: int
    product_id: int
    quantity: Decimal
    unit_kg: Decimal
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "quantity", _decimal(self.quantity))
        object.__setattr__(self, "unit_kg", _decimal(self.unit_kg))

    @property
    def kilos(self) -> Decimal:
        return _decimal(self.quantity * self.unit_kg)


@dataclass(frozen=True)
class FixedPallet:
    sequence: int
    allocations: tuple[DistributionAllocation, ...]
    locked: bool = True

    @property
    def total_kg(self) -> Decimal:
        return _decimal(sum((item.kilos for item in self.allocations), Decimal("0")))


@dataclass(frozen=True)
class ProposedPallet:
    sequence: int
    allocations: tuple[DistributionAllocation, ...]
    locked: bool = False

    @property
    def total_kg(self) -> Decimal:
        return _decimal(sum((item.kilos for item in self.allocations), Decimal("0")))

    @property
    def client_count(self) -> int:
        return len({item.client_id for item in self.allocations})

    @property
    def product_count(self) -> int:
        return len({item.product_id for item in self.allocations})


@dataclass(frozen=True)
class DistributionProposal:
    pallets: tuple[ProposedPallet, ...]
    pending: tuple[DistributionLine, ...]
    max_kg_per_pallet: Decimal

    @property
    def assigned_kg(self) -> Decimal:
        return _decimal(sum((pallet.total_kg for pallet in self.pallets), Decimal("0")))

    @property
    def pending_kg(self) -> Decimal:
        return _decimal(sum((line.kilos for line in self.pending), Decimal("0")))

    @property
    def is_complete(self) -> bool:
        return not self.pending


class PalletDistributionService:
    """Construye una propuesta determinista sin depender de PyQt ni de la base de datos.

    La heuristica respeta cantidades, pallets fijados y la regla operativa de
    un unico cliente por pallet. Dentro de ese cliente prioriza destino,
    producto y aprovechamiento de capacidad.
    """

    def propose(
        self,
        *,
        lines: Iterable[DistributionLine],
        pallet_sequences: Iterable[int],
        max_kg_per_pallet,
        fixed_pallets: Iterable[FixedPallet] = (),
    ) -> DistributionProposal:
        max_kg = _decimal(max_kg_per_pallet)
        if max_kg <= 0:
            raise ValueError("El maximo de kg por pallet debe ser mayor a cero.")

        sequences = tuple(sorted({int(sequence) for sequence in pallet_sequences}))
        if not sequences:
            raise ValueError("Debe existir al menos un pallet para proponer la distribucion.")

        requested = self._merge_lines(lines)
        fixed_by_sequence = {pallet.sequence: pallet for pallet in fixed_pallets}
        unknown_fixed = set(fixed_by_sequence) - set(sequences)
        if unknown_fixed:
            raise ValueError("Hay pallets fijados que no pertenecen a la preparacion actual.")

        remaining = self._subtract_fixed(requested, fixed_by_sequence.values())
        working: dict[int, list[DistributionAllocation]] = {}
        locked_sequences: set[int] = set()
        for sequence in sequences:
            fixed = fixed_by_sequence.get(sequence)
            if fixed is None:
                working[sequence] = []
                continue
            if fixed.total_kg > max_kg:
                raise ValueError(f"El pallet fijado {sequence} supera el maximo configurado.")
            if len({item.client_id for item in fixed.allocations}) > 1:
                raise ValueError(
                    f"El pallet fijado {sequence} contiene mercaderia de mas de un cliente."
                )
            working[sequence] = list(fixed.allocations)
            if fixed.locked:
                locked_sequences.add(sequence)

        ordered_lines = sorted(
            remaining,
            key=lambda line: (
                line.client_id,
                line.destination_id,
                -line.kilos,
                line.product_id,
            ),
        )
        pending: list[DistributionLine] = []
        for line in ordered_lines:
            pending.extend(
                self._place_line(
                    line=line,
                    working=working,
                    locked_sequences=locked_sequences,
                    max_kg=max_kg,
                )
            )

        pallets = tuple(
            ProposedPallet(
                sequence=sequence,
                allocations=tuple(working[sequence]),
                locked=sequence in locked_sequences,
            )
            for sequence in sequences
        )
        return DistributionProposal(
            pallets=pallets,
            pending=tuple(pending),
            max_kg_per_pallet=max_kg,
        )

    def _merge_lines(self, lines: Iterable[DistributionLine]) -> tuple[DistributionLine, ...]:
        quantities: dict[tuple[int, int, int, Decimal, str], Decimal] = defaultdict(
            lambda: Decimal("0.000")
        )
        for line in lines:
            key = (
                line.destination_id,
                line.client_id,
                line.product_id,
                line.unit_kg,
                line.label,
            )
            quantities[key] = _decimal(quantities[key] + line.quantity)
        return tuple(
            DistributionLine(
                destination_id=key[0],
                client_id=key[1],
                product_id=key[2],
                unit_kg=key[3],
                label=key[4],
                quantity=quantity,
            )
            for key, quantity in quantities.items()
            if quantity > 0
        )

    def _subtract_fixed(
        self,
        requested: tuple[DistributionLine, ...],
        fixed_pallets: Iterable[FixedPallet],
    ) -> tuple[DistributionLine, ...]:
        fixed_quantity: dict[tuple[int, int, int], Decimal] = defaultdict(
            lambda: Decimal("0.000")
        )
        for pallet in fixed_pallets:
            for allocation in pallet.allocations:
                key = (
                    allocation.destination_id,
                    allocation.client_id,
                    allocation.product_id,
                )
                fixed_quantity[key] = _decimal(fixed_quantity[key] + allocation.quantity)

        remaining: list[DistributionLine] = []
        for line in requested:
            key = (line.destination_id, line.client_id, line.product_id)
            assigned = min(line.quantity, fixed_quantity[key])
            fixed_quantity[key] = _decimal(fixed_quantity[key] - assigned)
            quantity = _decimal(line.quantity - assigned)
            if quantity > 0:
                remaining.append(
                    DistributionLine(
                        destination_id=line.destination_id,
                        client_id=line.client_id,
                        product_id=line.product_id,
                        quantity=quantity,
                        unit_kg=line.unit_kg,
                        label=line.label,
                    )
                )

        if any(quantity > 0 for quantity in fixed_quantity.values()):
            raise ValueError("Los pallets fijados contienen cantidades que no pertenecen a la orden.")
        return tuple(remaining)

    def _place_line(
        self,
        *,
        line: DistributionLine,
        working: dict[int, list[DistributionAllocation]],
        locked_sequences: set[int],
        max_kg: Decimal,
    ) -> list[DistributionLine]:
        remaining = line.quantity
        while remaining > 0:
            candidates = [
                sequence
                for sequence in working
                if sequence not in locked_sequences
                and self._pallet_accepts_client(working[sequence], line.client_id)
                and self._available_kg(working[sequence], max_kg) >= line.unit_kg
            ]
            if not candidates:
                return [
                    DistributionLine(
                        destination_id=line.destination_id,
                        client_id=line.client_id,
                        product_id=line.product_id,
                        quantity=remaining,
                        unit_kg=line.unit_kg,
                        label=line.label,
                    )
                ]

            sequence = max(
                candidates,
                key=lambda candidate: self._pallet_score(
                    allocations=working[candidate],
                    line=line,
                    max_kg=max_kg,
                ),
            )
            available_kg = self._available_kg(working[sequence], max_kg)
            units_that_fit = (available_kg / line.unit_kg).quantize(QUANTUM, rounding=ROUND_DOWN)
            quantity = min(remaining, units_that_fit)
            if quantity <= 0:
                return [
                    DistributionLine(
                        destination_id=line.destination_id,
                        client_id=line.client_id,
                        product_id=line.product_id,
                        quantity=remaining,
                        unit_kg=line.unit_kg,
                        label=line.label,
                    )
                ]
            self._append_allocation(working[sequence], line, quantity)
            remaining = _decimal(remaining - quantity)
        return []

    def _pallet_accepts_client(
        self,
        allocations: list[DistributionAllocation],
        client_id: int,
    ) -> bool:
        if not allocations:
            return True
        return all(item.client_id == client_id for item in allocations)

    def _available_kg(
        self,
        allocations: list[DistributionAllocation],
        max_kg: Decimal,
    ) -> Decimal:
        used = sum((allocation.kilos for allocation in allocations), Decimal("0"))
        return _decimal(max_kg - used)

    def _pallet_score(
        self,
        *,
        allocations: list[DistributionAllocation],
        line: DistributionLine,
        max_kg: Decimal,
    ) -> tuple[int, int, Decimal, int]:
        same_product = any(
            item.destination_id == line.destination_id
            and item.client_id == line.client_id
            and item.product_id == line.product_id
            for item in allocations
        )
        same_destination = any(
            item.client_id == line.client_id and item.destination_id == line.destination_id
            for item in allocations
        )
        used = _decimal(max_kg - self._available_kg(allocations, max_kg))
        # max() prefiere: mismo producto, mismo destino, pallet mas utilizado y,
        # ante empate, menor cantidad de lineas para mantener la propuesta estable.
        return (
            1 if same_product else 0,
            1 if same_destination else 0,
            used,
            -len(allocations),
        )

    def _append_allocation(
        self,
        allocations: list[DistributionAllocation],
        line: DistributionLine,
        quantity: Decimal,
    ) -> None:
        for index, existing in enumerate(allocations):
            if (
                existing.destination_id == line.destination_id
                and existing.client_id == line.client_id
                and existing.product_id == line.product_id
            ):
                allocations[index] = DistributionAllocation(
                    destination_id=existing.destination_id,
                    client_id=existing.client_id,
                    product_id=existing.product_id,
                    quantity=_decimal(existing.quantity + quantity),
                    unit_kg=existing.unit_kg,
                    label=existing.label,
                )
                return
        allocations.append(
            DistributionAllocation(
                destination_id=line.destination_id,
                client_id=line.client_id,
                product_id=line.product_id,
                quantity=quantity,
                unit_kg=line.unit_kg,
                label=line.label,
            )
        )

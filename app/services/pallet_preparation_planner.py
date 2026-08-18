from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.services.pallet_distribution_service import (
    DistributionAllocation,
    DistributionLine,
    DistributionProposal,
    FixedPallet,
    PalletDistributionService,
)


@dataclass(frozen=True)
class PreparedProposal:
    """Propuesta lista para consumir desde la UI sin mutar el borrador actual."""

    proposal: DistributionProposal
    pallet_drafts: tuple[dict, ...]
    pending_rows: tuple[dict, ...]

    @property
    def is_complete(self) -> bool:
        return self.proposal.is_complete


class PalletPreparationPlanner:
    """Adapta los drafts actuales de Preparacion de pallets al motor automatico.

    Este servicio contiene la frontera entre la forma que usa la UI actual
    (destinations/pallet drafts) y PalletDistributionService. La propuesta es
    inmutable: el widget puede mostrarla y recien copiarla a su estado cuando
    el operador la acepte.
    """

    def __init__(self, distribution_service: PalletDistributionService | None = None):
        self.distribution_service = distribution_service or PalletDistributionService()

    def propose(
        self,
        *,
        destinations: list[dict],
        pallets: list[dict],
        product_weights: Mapping[int, Decimal],
        max_kg_per_pallet,
        locked_sequences: set[int] | frozenset[int] = frozenset(),
        preserve_unlocked_allocations: bool = False,
    ) -> PreparedProposal:
        if not pallets:
            raise ValueError("Debe agregar al menos un pallet antes de proponer la distribucion.")

        lines = self._requested_lines(destinations, product_weights)
        fixed_pallets = self._fixed_pallets(
            pallets=pallets,
            locked_sequences=set(locked_sequences),
            product_weights=product_weights,
            preserve_unlocked_allocations=preserve_unlocked_allocations,
        )
        proposal = self.distribution_service.propose(
            lines=lines,
            pallet_sequences=[int(pallet["sequence"]) for pallet in pallets],
            max_kg_per_pallet=max_kg_per_pallet,
            fixed_pallets=fixed_pallets,
        )
        return PreparedProposal(
            proposal=proposal,
            pallet_drafts=self._proposal_drafts(proposal, destinations),
            pending_rows=self._pending_rows(proposal, destinations),
        )

    def _requested_lines(
        self,
        destinations: list[dict],
        product_weights: Mapping[int, Decimal],
    ) -> tuple[DistributionLine, ...]:
        lines: list[DistributionLine] = []
        for destination in destinations:
            for product in destination.get("products") or []:
                product_id = int(product["product_id"])
                unit_kg = self._weight_for(product_id, product_weights)
                quantity = Decimal(str(product.get("quantity") or 0))
                if quantity <= 0:
                    continue
                lines.append(
                    DistributionLine(
                        destination_id=int(destination["address_id"]),
                        client_id=int(destination["client_id"]),
                        product_id=product_id,
                        quantity=quantity,
                        unit_kg=unit_kg,
                        label=self._line_label(destination, product),
                    )
                )
        if not lines:
            raise ValueError("La orden no tiene mercaderia para distribuir.")
        return tuple(lines)

    def _fixed_pallets(
        self,
        *,
        pallets: list[dict],
        locked_sequences: set[int],
        product_weights: Mapping[int, Decimal],
        preserve_unlocked_allocations: bool,
    ) -> tuple[FixedPallet, ...]:
        fixed: list[FixedPallet] = []
        for pallet in pallets:
            sequence = int(pallet["sequence"])
            is_locked = sequence in locked_sequences
            if not is_locked and not preserve_unlocked_allocations:
                continue
            allocations = tuple(
                self._distribution_allocation(allocation, product_weights)
                for allocation in pallet.get("allocations") or []
            )
            if not allocations and not is_locked:
                continue
            fixed.append(
                FixedPallet(
                    sequence=sequence,
                    allocations=allocations,
                    locked=is_locked or preserve_unlocked_allocations,
                )
            )
        return tuple(fixed)

    def _distribution_allocation(
        self,
        allocation: dict,
        product_weights: Mapping[int, Decimal],
    ) -> DistributionAllocation:
        product_id = int(allocation["product_id"])
        unit_kg = Decimal(
            str(allocation.get("peso_unitario_kg") or self._weight_for(product_id, product_weights))
        )
        return DistributionAllocation(
            destination_id=int(allocation["address_id"]),
            client_id=int(allocation["client_id"]),
            product_id=product_id,
            quantity=Decimal(str(allocation["quantity"])),
            unit_kg=unit_kg,
            label=str(allocation.get("product_label") or ""),
        )

    def _proposal_drafts(
        self,
        proposal: DistributionProposal,
        destinations: list[dict],
    ) -> tuple[dict, ...]:
        product_labels = {
            (int(destination["address_id"]), int(product["product_id"])): str(product["product_label"])
            for destination in destinations
            for product in destination.get("products") or []
        }
        return tuple(
            {
                "sequence": pallet.sequence,
                "pallet_type_id": None,
                "locked": pallet.locked,
                "allocations": [
                    {
                        "client_id": allocation.client_id,
                        "address_id": allocation.destination_id,
                        "product_id": allocation.product_id,
                        "product_label": product_labels.get(
                            (allocation.destination_id, allocation.product_id), allocation.label
                        ),
                        "quantity": float(allocation.quantity),
                        "peso_unitario_kg": allocation.unit_kg,
                    }
                    for allocation in pallet.allocations
                ],
            }
            for pallet in proposal.pallets
        )

    def _pending_rows(
        self,
        proposal: DistributionProposal,
        destinations: list[dict],
    ) -> tuple[dict, ...]:
        destination_map = {
            int(destination["address_id"]): destination for destination in destinations
        }
        rows: list[dict] = []
        for line in proposal.pending:
            destination = destination_map.get(line.destination_id, {})
            product = next(
                (
                    item
                    for item in destination.get("products") or []
                    if int(item["product_id"]) == line.product_id
                ),
                {},
            )
            rows.append(
                {
                    "client_id": line.client_id,
                    "address_id": line.destination_id,
                    "product_id": line.product_id,
                    "client_label": destination.get("client_label") or f"Cliente {line.client_id}",
                    "address_label": destination.get("address_label") or f"Destino {line.destination_id}",
                    "product_label": product.get("product_label") or line.label,
                    "quantity": line.quantity,
                    "peso_unitario_kg": line.unit_kg,
                    "pending_kg": line.kilos,
                }
            )
        return tuple(rows)

    @staticmethod
    def _line_label(destination: dict, product: dict) -> str:
        return " / ".join(
            filter(
                None,
                (
                    str(destination.get("client_label") or ""),
                    str(destination.get("address_label") or ""),
                    str(product.get("product_label") or ""),
                ),
            )
        )

    @staticmethod
    def _weight_for(product_id: int, product_weights: Mapping[int, Decimal]) -> Decimal:
        if product_id not in product_weights:
            raise ValueError(f"Falta configurar el peso del articulo {product_id}.")
        weight = Decimal(str(product_weights[product_id])).quantize(Decimal("0.001"))
        if weight <= 0:
            raise ValueError(f"El articulo {product_id} no tiene un peso valido.")
        return weight

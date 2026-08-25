from decimal import Decimal

import pytest

from app.services.pallet_distribution_service import (
    DistributionAllocation,
    DistributionLine,
    FixedPallet,
    PalletDistributionService,
)


service = PalletDistributionService()


def line(*, destination, client, product, quantity, unit_kg, label=""):
    return DistributionLine(
        destination_id=destination,
        client_id=client,
        product_id=product,
        quantity=Decimal(str(quantity)),
        unit_kg=Decimal(str(unit_kg)),
        label=label,
    )


def allocation(*, destination, client, product, quantity, unit_kg, label=""):
    return DistributionAllocation(
        destination_id=destination,
        client_id=client,
        product_id=product,
        quantity=Decimal(str(quantity)),
        unit_kg=Decimal(str(unit_kg)),
        label=label,
    )


def test_distributes_multiple_clients_and_products_without_exceeding_capacity():
    proposal = service.propose(
        lines=(
            line(destination=10, client=1, product=100, quantity=40, unit_kg=25, label="Cardozo nativa"),
            line(destination=10, client=1, product=101, quantity=30, unit_kg=10, label="Cardozo 10kg"),
            line(destination=20, client=2, product=100, quantity=20, unit_kg=25, label="Torikos nativa"),
        ),
        pallet_sequences=(1, 2, 3),
        max_kg_per_pallet=1000,
    )

    assert proposal.is_complete
    assert proposal.pending == ()
    assert proposal.assigned_kg == Decimal("1800.000")
    assert all(pallet.total_kg <= Decimal("1000.000") for pallet in proposal.pallets)
    assert all(pallet.client_count <= 1 for pallet in proposal.pallets)
    assert sum(len(pallet.allocations) for pallet in proposal.pallets) >= 3


def test_never_mixes_two_clients_in_the_same_pallet_even_with_free_capacity():
    proposal = service.propose(
        lines=(
            line(destination=10, client=1, product=100, quantity=20, unit_kg=25),
            line(destination=20, client=2, product=200, quantity=10, unit_kg=25),
        ),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
    )

    assert proposal.is_complete
    assert [pallet.client_count for pallet in proposal.pallets] == [1, 1]
    assert {item.client_id for item in proposal.pallets[0].allocations} != {
        item.client_id for item in proposal.pallets[1].allocations
    }
    assert proposal.pallets[0].total_kg == Decimal("500.000")
    assert proposal.pallets[1].total_kg == Decimal("250.000")


def test_allows_multiple_products_of_the_same_client_in_one_pallet():
    proposal = service.propose(
        lines=(
            line(destination=10, client=1, product=100, quantity=20, unit_kg=25),
            line(destination=10, client=1, product=101, quantity=25, unit_kg=10),
        ),
        pallet_sequences=(1,),
        max_kg_per_pallet=1000,
    )

    pallet = proposal.pallets[0]
    assert proposal.is_complete
    assert pallet.client_count == 1
    assert pallet.product_count == 2
    assert pallet.total_kg == Decimal("750.000")


def test_splits_a_product_between_pallets_when_it_does_not_fit_in_one():
    proposal = service.propose(
        lines=(line(destination=10, client=1, product=100, quantity=60, unit_kg=25),),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
    )

    quantities = [
        item.quantity
        for pallet in proposal.pallets
        for item in pallet.allocations
        if item.product_id == 100
    ]

    assert proposal.is_complete
    assert sum(quantities) == Decimal("60.000")
    assert len(quantities) == 2
    assert proposal.pallets[0].total_kg == Decimal("1000.000")
    assert proposal.pallets[1].total_kg == Decimal("500.000")


def test_preserves_locked_pallet_and_only_distributes_remaining_quantity():
    fixed = FixedPallet(
        sequence=2,
        allocations=(
            allocation(destination=10, client=1, product=100, quantity=20, unit_kg=25),
        ),
    )

    proposal = service.propose(
        lines=(line(destination=10, client=1, product=100, quantity=60, unit_kg=25),),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
        fixed_pallets=(fixed,),
    )

    pallet_2 = next(pallet for pallet in proposal.pallets if pallet.sequence == 2)
    pallet_1 = next(pallet for pallet in proposal.pallets if pallet.sequence == 1)

    assert proposal.is_complete
    assert pallet_2.locked is True
    assert pallet_2.allocations == fixed.allocations
    assert pallet_2.total_kg == Decimal("500.000")
    assert pallet_1.total_kg == Decimal("1000.000")


def test_unlocked_preexisting_pallet_only_accepts_its_existing_client():
    fixed = FixedPallet(
        sequence=1,
        locked=False,
        allocations=(
            allocation(destination=10, client=1, product=100, quantity=20, unit_kg=25),
        ),
    )

    proposal = service.propose(
        lines=(
            line(destination=10, client=1, product=100, quantity=20, unit_kg=25),
            line(destination=20, client=2, product=200, quantity=10, unit_kg=25),
        ),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
        fixed_pallets=(fixed,),
    )

    pallet_1 = next(pallet for pallet in proposal.pallets if pallet.sequence == 1)
    pallet_2 = next(pallet for pallet in proposal.pallets if pallet.sequence == 2)

    assert proposal.is_complete
    assert {item.client_id for item in pallet_1.allocations} == {1}
    assert {item.client_id for item in pallet_2.allocations} == {2}


def test_keeps_unassigned_remainder_when_total_capacity_is_insufficient():
    proposal = service.propose(
        lines=(line(destination=10, client=1, product=100, quantity=100, unit_kg=25),),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
    )

    assert proposal.is_complete is False
    assert proposal.assigned_kg == Decimal("2000.000")
    assert proposal.pending_kg == Decimal("500.000")
    assert proposal.pending[0].quantity == Decimal("20.000")


def test_prioritizes_same_destination_for_the_same_client():
    proposal = service.propose(
        lines=(
            line(destination=10, client=1, product=100, quantity=20, unit_kg=25),
            line(destination=10, client=1, product=101, quantity=20, unit_kg=25),
            line(destination=20, client=2, product=102, quantity=20, unit_kg=25),
        ),
        pallet_sequences=(1, 2),
        max_kg_per_pallet=1000,
    )

    first = proposal.pallets[0]
    destinations = {item.destination_id for item in first.allocations}

    assert proposal.is_complete
    assert destinations == {10}
    assert first.client_count == 1
    assert first.total_kg == Decimal("1000.000")


def test_rejects_fixed_pallet_with_multiple_clients():
    with pytest.raises(ValueError, match="mas de un cliente"):
        service.propose(
            lines=(
                line(destination=10, client=1, product=100, quantity=10, unit_kg=25),
                line(destination=20, client=2, product=200, quantity=10, unit_kg=25),
            ),
            pallet_sequences=(1,),
            max_kg_per_pallet=1000,
            fixed_pallets=(
                FixedPallet(
                    sequence=1,
                    allocations=(
                        allocation(destination=10, client=1, product=100, quantity=10, unit_kg=25),
                        allocation(destination=20, client=2, product=200, quantity=10, unit_kg=25),
                    ),
                ),
            ),
        )


def test_rejects_missing_weight_and_invalid_fixed_pallet():
    with pytest.raises(ValueError, match="peso unitario"):
        line(destination=10, client=1, product=100, quantity=1, unit_kg=0)

    with pytest.raises(ValueError, match="no pertenecen"):
        service.propose(
            lines=(line(destination=10, client=1, product=100, quantity=1, unit_kg=25),),
            pallet_sequences=(1,),
            max_kg_per_pallet=1000,
            fixed_pallets=(
                FixedPallet(
                    sequence=1,
                    allocations=(
                        allocation(destination=99, client=9, product=999, quantity=1, unit_kg=25),
                    ),
                ),
            ),
        )

from decimal import Decimal

import pytest

from app.services.pallet_preparation_planner import PalletPreparationPlanner


def _destinations():
    return [
        {
            "client_id": 10,
            "address_id": 100,
            "client_label": "Cliente A",
            "address_label": "Destino A",
            "products": [
                {
                    "product_id": 1,
                    "product_label": "Nativa 25 kg",
                    "quantity": 80,
                    "unit": "bolsa",
                },
                {
                    "product_id": 2,
                    "product_label": "Modificada 25 kg",
                    "quantity": 20,
                    "unit": "bolsa",
                },
            ],
        },
        {
            "client_id": 20,
            "address_id": 200,
            "client_label": "Cliente B",
            "address_label": "Destino B",
            "products": [
                {
                    "product_id": 3,
                    "product_label": "Fecula 10 kg",
                    "quantity": 20,
                    "unit": "bolsa",
                }
            ],
        },
    ]


def _empty_pallets(count=2):
    return [
        {"sequence": sequence, "pallet_type_id": None, "allocations": []}
        for sequence in range(1, count + 1)
    ]


def _weights():
    return {
        1: Decimal("25.000"),
        2: Decimal("25.000"),
        3: Decimal("10.000"),
    }


def test_proposal_is_preview_and_does_not_mutate_current_pallet_drafts():
    pallets = _empty_pallets(2)
    original = [dict(pallet, allocations=list(pallet["allocations"])) for pallet in pallets]

    prepared = PalletPreparationPlanner().propose(
        destinations=_destinations(),
        pallets=pallets,
        product_weights=_weights(),
        max_kg_per_pallet=Decimal("1500"),
    )

    assert pallets == original
    assert prepared.is_complete is True
    assert len(prepared.pallet_drafts) == 2
    assert sum(
        Decimal(str(allocation["quantity"])) * Decimal(str(allocation["peso_unitario_kg"]))
        for pallet in prepared.pallet_drafts
        for allocation in pallet["allocations"]
    ) == Decimal("2700.000")
    assert prepared.pending_rows == ()


def test_locked_pallet_is_preserved_when_reorganizing_pending_load():
    # La orden pesa 2.700 kg. Con un pallet fijado en 1.000 kg y maximo de
    # 1.500 kg por pallet hacen falta al menos dos pallets libres para poder
    # completar la redistribucion sin violar capacidad.
    pallets = _empty_pallets(3)
    pallets[0]["allocations"] = [
        {
            "client_id": 10,
            "address_id": 100,
            "product_id": 1,
            "product_label": "Nativa 25 kg",
            "quantity": 40,
            "peso_unitario_kg": Decimal("25.000"),
        }
    ]

    prepared = PalletPreparationPlanner().propose(
        destinations=_destinations(),
        pallets=pallets,
        product_weights=_weights(),
        max_kg_per_pallet=Decimal("1500"),
        locked_sequences={1},
    )

    pallet_1 = next(pallet for pallet in prepared.pallet_drafts if pallet["sequence"] == 1)
    pallet_2 = next(pallet for pallet in prepared.pallet_drafts if pallet["sequence"] == 2)
    assert pallet_1["locked"] is True
    assert pallet_1["allocations"] == pallets[0]["allocations"]
    assert pallet_2["allocations"]
    assert prepared.is_complete is True


def test_insufficient_capacity_returns_structured_pending_rows_for_grid():
    prepared = PalletPreparationPlanner().propose(
        destinations=_destinations(),
        pallets=_empty_pallets(1),
        product_weights=_weights(),
        max_kg_per_pallet=Decimal("1500"),
    )

    assert prepared.is_complete is False
    assert prepared.pending_rows
    first = prepared.pending_rows[0]
    assert set(first) >= {
        "client_label",
        "address_label",
        "product_label",
        "quantity",
        "pending_kg",
    }
    assert sum(row["pending_kg"] for row in prepared.pending_rows) == Decimal("1200.000")


def test_missing_product_weight_blocks_preview_instead_of_guessing():
    weights = _weights()
    weights.pop(2)

    with pytest.raises(ValueError, match="Falta configurar el peso"):
        PalletPreparationPlanner().propose(
            destinations=_destinations(),
            pallets=_empty_pallets(2),
            product_weights=weights,
            max_kg_per_pallet=Decimal("1500"),
        )


def test_preserve_unlocked_allocations_can_use_current_layout_as_fixed_base():
    pallets = _empty_pallets(3)
    pallets[0]["allocations"] = [
        {
            "client_id": 10,
            "address_id": 100,
            "product_id": 1,
            "product_label": "Nativa 25 kg",
            "quantity": 20,
            "peso_unitario_kg": Decimal("25.000"),
        }
    ]

    prepared = PalletPreparationPlanner().propose(
        destinations=_destinations(),
        pallets=pallets,
        product_weights=_weights(),
        max_kg_per_pallet=Decimal("1500"),
        preserve_unlocked_allocations=True,
    )

    pallet_1 = next(pallet for pallet in prepared.pallet_drafts if pallet["sequence"] == 1)
    assert pallet_1["allocations"][0]["quantity"] == 20
    assert prepared.is_complete is True

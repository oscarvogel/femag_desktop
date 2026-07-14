from decimal import Decimal

from app.services.pallet_composition_service import (
    AllocationDraft,
    PalletCompositionService,
    PalletDraft,
    RequestedLine,
)


def test_reconcile_mixed_pallets_and_split_lines():
    result = PalletCompositionService().reconcile(
        requested=[
            RequestedLine(destination_id=1, product_id=10, quantity=Decimal("40"), label="Cliente A / Articulo A"),
            RequestedLine(destination_id=2, product_id=20, quantity=Decimal("5"), label="Cliente B / Articulo B"),
        ],
        pallets=[
            PalletDraft(
                sequence=1,
                allocations=(
                    AllocationDraft(1, 10, Decimal("25"), Decimal("2.5"), "Cliente A / Articulo A"),
                ),
            ),
            PalletDraft(
                sequence=2,
                allocations=(
                    AllocationDraft(1, 10, Decimal("15"), Decimal("2.5"), "Cliente A / Articulo A"),
                    AllocationDraft(2, 20, Decimal("5"), Decimal("10"), "Cliente B / Articulo B"),
                ),
            ),
        ],
    )

    assert result.total_kg == Decimal("150.000")
    assert result.pallets[0].total_kg == Decimal("62.500")
    assert result.pallets[1].total_kg == Decimal("87.500")
    assert result.is_complete is True
    assert result.can_issue is True
    assert result.issues == ()


def test_reconcile_reports_pending_excess_and_zero_weight():
    result = PalletCompositionService().reconcile(
        requested=[
            RequestedLine(1, 10, Decimal("10"), "Cliente A / Articulo A"),
            RequestedLine(2, 20, Decimal("5"), "Cliente B / Articulo B"),
            RequestedLine(3, 30, Decimal("1"), "Cliente C / Articulo C"),
        ],
        pallets=[
            PalletDraft(
                sequence=1,
                allocations=(
                    AllocationDraft(1, 10, Decimal("5"), Decimal("2.5"), "Cliente A / Articulo A"),
                    AllocationDraft(2, 20, Decimal("6"), Decimal("3"), "Cliente B / Articulo B"),
                    AllocationDraft(3, 30, Decimal("1"), Decimal("0"), "Cliente C / Articulo C"),
                ),
            ),
        ],
    )

    assert [issue.code for issue in result.issues] == ["pending", "excess", "zero_weight"]
    assert result.pending_quantity == Decimal("5.000")
    assert result.can_issue is False


def test_reconcile_without_pallets_is_an_incomplete_draft():
    result = PalletCompositionService().reconcile(
        requested=[RequestedLine(1, 10, Decimal("10"), "Cliente A / Articulo A")],
        pallets=[],
    )

    assert result.total_kg == Decimal("0.000")
    assert result.is_complete is False
    assert result.can_issue is False
    assert [issue.code for issue in result.issues] == ["no_pallets", "pending"]

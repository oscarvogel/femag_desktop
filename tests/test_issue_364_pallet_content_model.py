"""Contenido de pallet con lote/fecha propio (#364)."""

from datetime import date
from decimal import Decimal

from conftest import _master_data

from app.config.schema import _backfill_allocation_lote
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)


def _scenario():
    data = _master_data()
    order = LoadOrder.create(
        order_number=96001,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_PENDING,
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=data["address"],
        sequence=1,
    )
    line = LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=120,
        unit="bolsa",
        lote="LOTE-LEGACY",
        fecha_elaboracion=date(2026, 10, 20),
        fecha_envasado=date(2026, 10, 19),
    )
    pallet_a = LoadOrderPallet.create(order=order, sequence=1)
    pallet_b = LoadOrderPallet.create(order=order, sequence=2)
    allocation_a = LoadOrderPalletAllocation.create(
        pallet=pallet_a,
        destination=destination,
        product=data["product"],
        quantity=60,
        peso_unitario_kg=Decimal("25"),
    )
    allocation_b = LoadOrderPalletAllocation.create(
        pallet=pallet_b,
        destination=destination,
        product=data["product"],
        quantity=60,
        peso_unitario_kg=Decimal("25"),
    )
    existing = LoadOrderPalletAllocation.create(
        pallet=pallet_b,
        destination=destination,
        product=data["other_product"],
        quantity=10,
        peso_unitario_kg=Decimal("1"),
        lote="LOTE-PROPIO",
        fecha_elaboracion=date(2026, 10, 21),
        fecha_envasado=date(2026, 10, 18),
    )
    loose = LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=20,
        peso_unitario_kg=Decimal("25"),
    )
    return data, line, allocation_a, allocation_b, existing, loose


def test_backfill_copies_line_lote_to_pallet_contents(db):
    data, line, allocation_a, allocation_b, existing, loose = _scenario()

    _backfill_allocation_lote(db)

    allocation_a = LoadOrderPalletAllocation.get_by_id(allocation_a.id)
    allocation_b = LoadOrderPalletAllocation.get_by_id(allocation_b.id)
    existing = LoadOrderPalletAllocation.get_by_id(existing.id)
    loose = LoadOrderLooseAllocation.get_by_id(loose.id)

    assert allocation_a.lote == line.lote
    assert allocation_a.fecha_elaboracion == line.fecha_elaboracion
    assert allocation_a.fecha_envasado == line.fecha_envasado
    assert allocation_b.lote == line.lote
    assert allocation_b.fecha_elaboracion == line.fecha_elaboracion
    assert allocation_b.fecha_envasado == line.fecha_envasado
    assert existing.lote == "LOTE-PROPIO"
    assert existing.fecha_elaboracion == date(2026, 10, 21)
    assert existing.fecha_envasado == date(2026, 10, 18)
    assert loose.lote == line.lote
    assert loose.fecha_elaboracion == line.fecha_elaboracion
    assert loose.fecha_envasado == line.fecha_envasado


def test_contents_keep_independent_lote_and_date(db):
    data, _, allocation_a, allocation_b, _, _ = _scenario()

    allocation_a.lote = "LOTE-A"
    allocation_a.fecha_elaboracion = date(2026, 10, 22)
    allocation_a.fecha_envasado = date(2026, 10, 21)
    allocation_a.save(
        only=[
            LoadOrderPalletAllocation.lote,
            LoadOrderPalletAllocation.fecha_elaboracion,
            LoadOrderPalletAllocation.fecha_envasado,
        ]
    )
    allocation_b.lote = "LOTE-B"
    allocation_b.fecha_elaboracion = date(2026, 10, 23)
    allocation_b.fecha_envasado = date(2026, 10, 22)
    allocation_b.save(
        only=[
            LoadOrderPalletAllocation.lote,
            LoadOrderPalletAllocation.fecha_elaboracion,
            LoadOrderPalletAllocation.fecha_envasado,
        ]
    )

    allocation_a = LoadOrderPalletAllocation.get_by_id(allocation_a.id)
    allocation_b = LoadOrderPalletAllocation.get_by_id(allocation_b.id)

    assert (
        allocation_a.lote,
        allocation_a.fecha_elaboracion,
        allocation_a.fecha_envasado,
    ) == (
        "LOTE-A",
        date(2026, 10, 22),
        date(2026, 10, 21),
    )
    assert (
        allocation_b.lote,
        allocation_b.fecha_elaboracion,
        allocation_b.fecha_envasado,
    ) == (
        "LOTE-B",
        date(2026, 10, 23),
        date(2026, 10, 22),
    )

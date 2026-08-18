from decimal import Decimal

import pytest


def test_global_pallet_capacity_requires_explicit_configuration(db):
    from app.services.pallet_capacity_service import PalletCapacityService

    assert PalletCapacityService.pallet_max_kg() is None

    saved = PalletCapacityService.set_pallet_max_kg("1450")

    assert saved == Decimal("1450.000")
    assert PalletCapacityService.pallet_max_kg() == Decimal("1450.000")


def test_global_pallet_capacity_rejects_invalid_values(db):
    from app.services.pallet_capacity_service import PalletCapacityService

    for value in (0, -1, "", "abc"):
        with pytest.raises(ValueError):
            PalletCapacityService.set_pallet_max_kg(value)


def test_truck_capacity_can_be_set_and_cleared(db):
    from app.models.masters import Carrier, Truck
    from app.services.pallet_capacity_service import PalletCapacityService

    carrier = Carrier.create(name="Transportista capacidad")
    truck = Truck.create(domain="CAP298", carrier=carrier)

    assert PalletCapacityService.truck_max_load_kg(truck) is None

    saved = PalletCapacityService.set_truck_max_load_kg(truck, "28500")
    truck = Truck.get_by_id(truck.id)

    assert saved == Decimal("28500.000")
    assert truck.max_load_kg == Decimal("28500.000")
    assert PalletCapacityService.truck_max_load_kg(truck) == Decimal("28500.000")

    PalletCapacityService.clear_truck_max_load_kg(truck)
    truck = Truck.get_by_id(truck.id)

    assert truck.max_load_kg is None
    assert PalletCapacityService.truck_max_load_kg(truck) is None


def test_truck_capacity_rejects_non_positive_values(db):
    from app.models.masters import Truck
    from app.services.pallet_capacity_service import PalletCapacityService

    truck = Truck.create(domain="CAP299")

    with pytest.raises(ValueError, match="mayor a cero"):
        PalletCapacityService.set_truck_max_load_kg(truck, 0)

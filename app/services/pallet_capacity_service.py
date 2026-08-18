from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.masters import Truck
from app.models.system import AppParameter


PALLET_MAX_KG_KEY = "pallet_max_kg"


def _decimal(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("La capacidad debe ser un numero valido.") from exc
    if result <= 0:
        raise ValueError("La capacidad debe ser mayor a cero.")
    return result


class PalletCapacityService:
    """Centraliza limites de peso usados por Preparacion de pallets."""

    @classmethod
    def pallet_max_kg(cls) -> Decimal | None:
        row = AppParameter.get_or_none(AppParameter.key == PALLET_MAX_KG_KEY)
        if row is None or not (row.value or "").strip():
            return None
        try:
            return _decimal(row.value)
        except ValueError:
            return None

    @classmethod
    def set_pallet_max_kg(cls, value) -> Decimal:
        normalized = _decimal(value)
        row, _created = AppParameter.get_or_create(
            key=PALLET_MAX_KG_KEY,
            defaults={"value": format(normalized, "f")},
        )
        row.value = format(normalized, "f")
        row.save()
        return normalized

    @classmethod
    def truck_max_load_kg(cls, truck: Truck | None) -> Decimal | None:
        if truck is None or truck.max_load_kg is None:
            return None
        value = Decimal(str(truck.max_load_kg)).quantize(Decimal("0.001"))
        return value if value > 0 else None

    @classmethod
    def set_truck_max_load_kg(cls, truck: Truck, value) -> Decimal:
        normalized = _decimal(value)
        truck.max_load_kg = normalized
        truck.save()
        return normalized

    @classmethod
    def clear_truck_max_load_kg(cls, truck: Truck) -> None:
        truck.max_load_kg = None
        truck.save()

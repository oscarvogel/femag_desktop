"""Datos sinteticos para una instancia demo de FEMAG Web (#803).

Crea un usuario administrador, maestros minimos y una orden de carga con dos
renglones para poder probar el flujo QR sin copiar datos reales de la fabrica.

Se ejecuta solo en la base demo de la webapp. Nunca debe apuntar a la MySQL de
produccion: por eso exige ``FEMAG_DEMO=1`` o ``FEMAG_WEB_ALLOW_DEMO_SEED=1``.
Es idempotente: volver a correrlo no duplica la orden ni el usuario.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import (
    CLIENT_ADDRESS_TYPE_DELIVERY,
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService

DEFAULT_ADMIN_USER = "demo"
DEFAULT_ORDER_TOKEN = "demo-web-order-2026"
DEFAULT_ORDER_NUMBER = 990001


def _demo_enabled() -> bool:
    flag = os.getenv("FEMAG_DEMO", "").strip().lower()
    allow = os.getenv("FEMAG_WEB_ALLOW_DEMO_SEED", "").strip().lower()
    return flag in {"1", "true", "yes", "si", "sí", "on"} or allow in {
        "1",
        "true",
        "yes",
        "si",
        "sí",
        "on",
    }


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(
            f"Falta {name}. Definila para crear el administrador demo."
        )
    return value


def _master_data() -> dict:
    client, _ = Client.get_or_create(
        name="CLIENTE DEMO WEB",
        defaults={"cuit": "30999999991", "iva_condition": "RI", "active": True},
    )
    address, _ = ClientAddress.get_or_create(
        client=client,
        address_type=CLIENT_ADDRESS_TYPE_DELIVERY,
        address="Ruta Demo km 1",
        defaults={
            "province": "Misiones",
            "city": "Posadas",
            "is_primary": True,
        },
    )
    carrier, _ = Carrier.get_or_create(
        name="TRANSPORTE DEMO WEB",
        defaults={"cuit": "30999999992", "active": True},
    )
    truck, _ = Truck.get_or_create(
        domain="DEMO001",
        defaults={"carrier": carrier, "active": True},
    )
    driver, _ = Driver.get_or_create(
        name="CHOFER DEMO WEB",
        defaults={"carrier": carrier, "document": "99999999", "active": True},
    )
    product_bags, _ = Product.get_or_create(
        name="FECULA DEMO WEB 25KG",
        defaults={
            "unit": "bolsa",
            "peso_unitario_kg": Decimal("25.000"),
            "active": True,
        },
    )
    product_kg, _ = Product.get_or_create(
        name="ALMIDON DEMO WEB GRANEL",
        defaults={
            "unit": "kg",
            "peso_unitario_kg": Decimal("1000.000"),
            "active": True,
        },
    )
    return {
        "client": client,
        "address": address,
        "carrier": carrier,
        "truck": truck,
        "driver": driver,
        "product_bags": product_bags,
        "product_kg": product_kg,
    }


def _ensure_admin() -> User:
    username = os.getenv("FEMAG_WEB_DEMO_ADMIN_USER", DEFAULT_ADMIN_USER).strip()
    password = _required_env("FEMAG_WEB_DEMO_ADMIN_PASSWORD")
    permission_service = PermissionService()
    permission_service.seed_defaults()
    existing = User.get_or_none(User.username == username)
    if existing is not None:
        return existing
    return AuthService().create_user(
        username,
        password,
        "Administrador",
        display_name="Demo Web",
        actor="demo-seed",
    )


def _ensure_order(data: dict) -> LoadOrder:
    token = os.getenv("FEMAG_WEB_DEMO_ORDER_TOKEN", DEFAULT_ORDER_TOKEN).strip()
    if not token:
        raise SystemExit("FEMAG_WEB_DEMO_ORDER_TOKEN no puede estar vacio.")
    existing = LoadOrder.get_or_none(LoadOrder.qr_token == token)
    if existing is not None:
        return existing

    order_number = int(
        os.getenv("FEMAG_WEB_DEMO_ORDER_NUMBER", str(DEFAULT_ORDER_NUMBER))
    )
    if LoadOrder.get_or_none(LoadOrder.order_number == order_number) is not None:
        raise SystemExit(
            f"Ya existe una orden con el numero demo {order_number}. "
            "Defini otro FEMAG_WEB_DEMO_ORDER_NUMBER."
        )

    order = LoadOrder.create(
        order_number=order_number,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_ISSUED,
        qr_token=token,
        created_by="demo-seed",
        updated_by="demo-seed",
    )
    LoadOrderProduct.create(
        order=order,
        product=data["product_bags"],
        quantity=40,
        unit="bolsa",
    )
    LoadOrderProduct.create(
        order=order,
        product=data["product_kg"],
        quantity=100,
        unit="kg",
    )
    return order


def main() -> int:
    if not _demo_enabled():
        print(
            "Este script es solo para demo. Defini FEMAG_DEMO=1 o "
            "FEMAG_WEB_ALLOW_DEMO_SEED=1 para confirmar.",
            file=sys.stderr,
        )
        return 1

    database = initialize_runtime_database()
    try:
        database.connect(reuse_if_open=True)
        ensure_runtime_schema(database)
        user = _ensure_admin()
        data = _master_data()
        order = _ensure_order(data)
    finally:
        if not database.is_closed():
            database.close()

    base_url = os.getenv("FEMAG_WEB_PUBLIC_URL", "").strip().rstrip("/")
    orden_url = f"{base_url}/orden/{order.qr_token}" if base_url else ""
    print("Datos demo de FEMAG Web listos.")
    print(f"Usuario: {user.username}")
    print(f"Orden: {order.order_number} (token {order.qr_token})")
    if orden_url:
        print(f"URL: {orden_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

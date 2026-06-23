from __future__ import annotations

from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService


DEMO_PASSWORD = "demo"


def _user(username: str, profile_name: str) -> User:
    existing = User.get_or_none(User.username == username)
    if existing:
        return existing
    return AuthService().create_user(username, DEMO_PASSWORD, profile_name)


def _client(name: str, cuit: str, **kwargs) -> Client:
    client, _ = Client.get_or_create(
        cuit=cuit,
        defaults={"name": name, "iva_condition": kwargs.pop("iva_condition", "RI"), **kwargs},
    )
    return client


def _address(client: Client, address_type: str, address: str, *, is_primary: bool = False) -> ClientAddress:
    row, _ = ClientAddress.get_or_create(
        client=client,
        address_type=address_type,
        address=address,
        defaults={
            "province": "Misiones",
            "city": "Posadas",
            "is_primary": is_primary,
        },
    )
    return row


def seed_demo_data() -> dict[str, int]:
    PermissionService().seed_defaults()
    _user("admin", "Administrador")
    _user("secretaria", "Secretaría")
    _user("administracion", "Administración")
    _user("consulta", "Solo consulta")

    femag = _client(
        "Supermercados Andresito SRL",
        "30711111118",
        phone="0376 444-1000",
        email="compras@andresito.example",
        contact="María Benítez",
    )
    _address(femag, "fiscal", "Av. San Martín 1200")
    _address(femag, "entrega", "Depósito Ruta 12 km 8", is_primary=True)
    _address(femag, "entrega", "Sucursal Garupá")

    litoral = _client(
        "Distribuidora Litoral SA",
        "30722222229",
        phone="0376 444-2000",
        email="logistica@litoral.example",
        contact="Carlos Duarte",
    )
    _address(litoral, "fiscal", "Bolívar 880")
    _address(litoral, "entrega", "Parque Industrial Posadas", is_primary=True)

    _client("Alimentos Oberá", "30733333330", phone="03755 421-100", email="pedidos@obera.example")

    fecula_mandioca, _ = Product.get_or_create(name="Fécula de mandioca", defaults={"unit": "kg"})
    fecula_maiz, _ = Product.get_or_create(name="Fécula de maíz", defaults={"unit": "kg"})
    otro_producto, _ = Product.get_or_create(name="Almidón modificado", defaults={"unit": "bolsa"})

    carrier, _ = Carrier.get_or_create(
        name="Transporte Guaraní",
        defaults={"cuit": "30744444441", "phone": "0376 444-3000"},
    )
    other_carrier, _ = Carrier.get_or_create(name="Expreso Misiones", defaults={"phone": "0376 444-4000"})
    truck, _ = Truck.get_or_create(domain="AB123CD", defaults={"carrier": carrier})
    Truck.get_or_create(domain="AC456EF", defaults={"carrier": other_carrier})

    blocked_driver, _ = Driver.get_or_create(
        name="Juan Pérez",
        defaults={"document": "20111222", "phone": "3764-111111"},
    )
    Driver.get_or_create(name="Pedro Gómez", defaults={"document": "20222333", "phone": "3764-222222"})

    standard_pallet, _ = PalletType.get_or_create(
        type="Pallet estándar",
        defaults={"measure": "1,00 x 1,20 m", "weight": 18.0},
    )
    PalletType.get_or_create(type="Pallet reforzado", defaults={"measure": "1,10 x 1,30 m", "weight": 24.5})

    if not LoadOrder.select().exists():
        delivery = ClientAddress.get(
            ClientAddress.client == femag,
            ClientAddress.address_type == "entrega",
            ClientAddress.is_primary == True,  # noqa: E712
        )
        LoadOrderService(current_user="admin").create_order(
            client=femag,
            delivery_address=delivery,
            carrier=carrier,
            driver=blocked_driver,
            truck=truck,
            products=[
                {"product": fecula_mandioca, "quantity": 1200, "unit": "kg"},
                {"product": fecula_maiz, "quantity": 600, "unit": "kg"},
            ],
            pallets=[
                {"pallet_type": standard_pallet, "quantity": 12},
            ],
            observations="Demo: orden activa para verificar bloqueo de chofer.",
        )

    return {
        "users": User.select().count(),
        "clients": Client.select().count(),
        "products": Product.select().count(),
        "drivers": Driver.select().count(),
        "carriers": Carrier.select().count(),
        "trucks": Truck.select().count(),
        "pallet_types": PalletType.select().count(),
        "load_orders": LoadOrder.select().count(),
    }


def main() -> int:
    summary = seed_demo_data()
    print("Datos demo FEMAG listos")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

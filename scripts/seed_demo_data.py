from __future__ import annotations

from pathlib import Path
import sys
import os


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from peewee import SqliteDatabase

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct, LoadOrderStatusHistory
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.models.system import BackupLog, NumberSequence
from app.services.permission_service import PermissionService


DEMO_DB_PATH = Path(os.environ.get("LOCALAPPDATA", ".")) / "FEMAG" / "femag_demo.sqlite3"
DEMO_ORDER_NUMBER = 9001


CLIENTS = (
    ("CANTERO FLAVIA", "30710000001", "Paso de los Libres", "Corrientes", "Ruta nacional 117"),
    ("GALEANO", "30710000002", "Chajarí", "Entre Ríos", "Av. 9 de Julio 1450"),
    ("ARAUJO", "30710000003", "José Ingenieros", "Buenos Aires", "San Martín 220"),
    ("TRIGOS DEL OESTE", "30710000004", "Castelar", "Buenos Aires", "Arias 3200"),
    ("PROD. CALEX", "30710000005", "La Unión, Distrito Ezeiza", "Buenos Aires", "Camino Real s/n"),
    ("BAKESUPLIES", "30710000006", "Don Roque", "Buenos Aires", "Parque industrial"),
    ("TORIKOS", "30710000007", "C.A.B.A.", "C.A.B.A.", "Av. Directorio 1800"),
)

PRODUCTS = (
    ("Fécula de mandioca x 25 kg", "bolsa x 25 kg"),
    ("Fécula de mandioca x 10 kg", "bolsa x 10 kg"),
    ("Almidón de maíz", "bolsa x 25 kg"),
    ("Pack x 10 un. x 1 kg", "pack"),
    ("Pallet x 1 kg", "pallet"),
)


def seed_demo_data(db_path: Path = DEMO_DB_PATH) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(db_path)
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS, safe=True)
    PermissionService().seed_defaults()

    clients = [_client(name, cuit, city, province, address) for name, cuit, city, province, address in CLIENTS]
    products = [_product(name, unit) for name, unit in PRODUCTS]
    carrier, _ = Carrier.get_or_create(name="GLIENKE EZEQUIEL", defaults={"cuit": "30720000001", "phone": "3764 555-010"})
    driver, _ = Driver.get_or_create(
        name="GLIENKE EZEQUIEL",
        defaults={"document": "DNI 30111222", "phone": "3764 555-011", "available": True},
    )
    truck, _ = Truck.get_or_create(domain="RIA609 / CIE907", defaults={"carrier": carrier})
    pallet, _ = PalletType.get_or_create(type="Pallet x 1 kg", defaults={"measure": "1,00 x 1,20", "weight": 18})

    order = LoadOrder.get_or_none(LoadOrder.order_number == DEMO_ORDER_NUMBER)
    if order is None:
        order = LoadOrder.create(
            order_number=DEMO_ORDER_NUMBER,
            client=clients[0],
            delivery_address=clients[0].addresses.where(ClientAddress.is_primary == True).get(),  # noqa: E712
            carrier=carrier,
            driver=driver,
            truck=truck,
            status=LoadOrder.STATUS_PENDING,
            observations="Demo FEMAG: varios destinatarios, lote L-2606 y vehículo limpio y apto.",
            created_by="demo",
            updated_by="demo",
        )
        _create_demo_details(order, products, pallet)
        LoadOrderStatusHistory.create(
            order=order,
            old_status=None,
            new_status=order.status,
            user="demo",
            observation="Orden demo creada para revisión visual",
        )

    Driver.update(available=False).where(Driver.id == driver.id).execute()
    sequence, _ = NumberSequence.get_or_create(name="load_order", defaults={"current_number": DEMO_ORDER_NUMBER})
    if sequence.current_number < DEMO_ORDER_NUMBER:
        sequence.current_number = DEMO_ORDER_NUMBER
        sequence.save()
    BackupLog.get_or_create(status="OK", file_path="demo/backup-femag.zip", message="Backup demo disponible")
    database.close()
    return db_path


def _client(name: str, cuit: str, city: str, province: str, address: str) -> Client:
    client, _ = Client.get_or_create(name=name, defaults={"cuit": cuit, "iva_condition": "Responsable inscripto"})
    ClientAddress.get_or_create(
        client=client,
        address_type="entrega",
        defaults={"province": province, "city": city, "address": address, "is_primary": True},
    )
    return client


def _product(name: str, unit: str) -> Product:
    return Product.get_or_create(name=name, defaults={"unit": unit})[0]


def _create_demo_details(order: LoadOrder, products: list[Product], pallet: PalletType) -> None:
    detail = (
        (products[0], 320, "bolsa x 25 kg", "CANTERO FLAVIA / Lote L-2606 / Elab. 12-06-2026"),
        (products[1], 140, "bolsa x 10 kg", "GALEANO / Lote L-2606 / Elab. 12-06-2026"),
        (products[3], 80, "pack", "TORIKOS / Lote L-2605 / Elab. 11-06-2026"),
        (products[0], 260, "bolsa x 25 kg", "TRIGOS DEL OESTE / Lote L-2606 / Elab. 12-06-2026"),
    )
    for product, quantity, unit, observations in detail:
        LoadOrderProduct.create(
            order=order,
            product=product,
            quantity=quantity,
            unit=unit,
            observations=observations,
        )
    LoadOrderPallet.create(order=order, pallet_type=pallet, measure=pallet.measure, weight=pallet.weight, quantity=18)


def main() -> int:
    path = seed_demo_data()
    print(f"Datos demo FEMAG listos en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

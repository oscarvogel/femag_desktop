import argparse
import sys
from pathlib import Path

from peewee import SqliteDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.models.security import User
from app.services.audit_history_service import AuditHistoryService
from app.services.auth_service import AuthService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService


DEFAULT_DATABASE_PATH = Path("femag_audit_demo.sqlite3")
DEFAULT_OUTPUT_DIR = Path("outputs") / "issue_472_audit_demo"
DEFAULT_USERNAME = "audit_demo"
DEFAULT_PASSWORD = "demo"


def _ensure_user(username: str, password: str) -> None:
    if User.get_or_none(User.username == username):
        return
    AuthService().create_user(username, password, "Administrador")


def _ensure_masters() -> dict:
    carrier, _ = Carrier.get_or_create(
        name="AUDIT472 Transporte Demo",
        defaults={"cuit": "30747200001", "phone": "3764-720001"},
    )
    driver, _ = Driver.get_or_create(
        name="AUDIT472 Chofer Demo",
        defaults={"carrier": carrier, "document": "D47200001", "phone": "3764-720002"},
    )
    driver.carrier = carrier
    driver.available = True
    driver.save()

    truck, _ = Truck.get_or_create(domain="AU472DE", defaults={"carrier": carrier})
    truck.carrier = carrier
    truck.save()

    client, _ = Client.get_or_create(
        cuit="30747200002",
        defaults={
            "name": "AUDIT472 Cliente Demo",
            "iva_condition": "RI",
            "contact": "Prueba controlada",
            "lista_precios": 1,
        },
    )
    client.name = "AUDIT472 Cliente Demo"
    client.lista_precios = 1
    client.save()

    address = ClientAddress.get_or_none(
        (ClientAddress.client == client)
        & (ClientAddress.address_type == "entrega")
        & (ClientAddress.address == "Ruta 12 km 1472")
    )
    if address is None:
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city="Puerto Rico",
            address="Ruta 12 km 1472",
            observations="Destino controlado para auditoría #472",
            is_primary=True,
        )

    iva = TipoIVA.iva_default()
    product, _ = Product.get_or_create(
        name="AUDIT472 Fécula Demo",
        defaults={
            "unit": "bolsas",
            "peso_unitario_kg": 25.0,
            "product_kind": "producto",
            "classification_source": "manual",
            "weight_source": "manual",
            "review_required": False,
            "precio_neto_base": 1000.0,
            "precio_lista_1": 1000.0,
            "precio_lista_2": 1050.0,
            "precio_lista_3": 1100.0,
            "precio_lista_4": 1150.0,
            "tipo_iva": iva,
        },
    )
    product.unit = "bolsas"
    product.peso_unitario_kg = 25.0
    product.product_kind = "producto"
    product.classification_source = "manual"
    product.weight_source = "manual"
    product.review_required = False
    product.precio_neto_base = 1000.0
    product.precio_lista_1 = 1000.0
    product.precio_lista_2 = 1050.0
    product.precio_lista_3 = 1100.0
    product.precio_lista_4 = 1150.0
    product.tipo_iva = iva
    product.save()

    return {
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "client": client,
        "address": address,
        "product": product,
    }


def _create_order(username: str, masters: dict, *, label: str, quantity: int = 40) -> LoadOrder:
    return LoadOrderService(current_user=username).create_order(
        carrier=masters["carrier"],
        driver=masters["driver"],
        truck=masters["truck"],
        destinations=[
            {
                "client": masters["client"],
                "delivery_address": masters["address"],
                "observations": f"Destino demo {label}",
                "products": [
                    {
                        "product": masters["product"],
                        "quantity": quantity,
                        "observations": f"Mercadería demo {label}",
                    }
                ],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": masters["client"],
                        "delivery_address": masters["address"],
                        "product": masters["product"],
                        "quantity": quantity,
                    }
                ],
            }
        ],
        observations=f"AUDIT472 {label}",
    )


def seed_controlled_audit_demo(
    database: SqliteDatabase,
    *,
    username: str = DEFAULT_USERNAME,
    password: str = DEFAULT_PASSWORD,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    PermissionService().seed_defaults()
    _ensure_user(username, password)
    masters = _ensure_masters()

    service = LoadOrderService(current_user=username)
    operations = LoadOrderOperationService(current_user=username, prints_dir=output_dir)

    pending = _create_order(username, masters, label="PENDIENTE_MODIFICADA", quantity=40)
    pending = service.update_order(
        pending,
        observations="AUDIT472 pendiente modificada para validar evento 'Orden modificada'",
    )

    emitted = _create_order(username, masters, label="EMITIDA_IMPRESA", quantity=50)
    emitted = operations.issue(emitted)
    pdf_path = operations.print_order(emitted)
    xlsx_path = operations.export_pallet_layout_xlsx(emitted)

    ready_to_annul = _create_order(username, masters, label="EMITIDA_PARA_ANULAR", quantity=60)
    ready_to_annul = operations.issue(ready_to_annul)

    history = AuditHistoryService()
    return {
        "pending": pending,
        "emitted": emitted,
        "ready_to_annul": ready_to_annul,
        "pdf_path": Path(pdf_path),
        "xlsx_path": Path(xlsx_path),
        "pending_events": history.load_order_history(pending),
        "emitted_events": history.load_order_history(emitted),
        "ready_events": history.load_order_history(ready_to_annul),
        "username": username,
        "password": password,
    }


def _print_summary(result: dict, database_path: Path) -> None:
    pending = result["pending"]
    emitted = result["emitted"]
    ready = result["ready_to_annul"]
    print("Seed controlado de auditoría #472 creado")
    print(f"Base SQLite: {database_path}")
    print(f"Usuario: {result['username']}")
    print(f"Clave: {result['password']}")
    print("")
    print(f"1) OC-{pending.order_number:06d} | {pending.status} | creada + modificada")
    print(f"2) OC-{emitted.order_number:06d} | {emitted.status} | creada + emitida + PDF + Excel")
    print(f"3) OC-{ready.order_number:06d} | {ready.status} | lista para ANULAR manualmente")
    print("")
    print(f"PDF evidencia: {result['pdf_path']}")
    print(f"Excel evidencia: {result['xlsx_path']}")
    print("")
    print("Para abrir esta base en FEMAG Desktop (PowerShell):")
    print('$env:FEMAG_SECURE_CONFIG="0"')
    print('$env:FEMAG_DB_ENGINE="sqlite"')
    print(f'$env:FEMAG_SQLITE_PATH="{database_path.as_posix()}"')
    print("py -m app.main --ui")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Crea una base SQLite aislada para probar el historial/auditoría del issue #472."
    )
    parser.add_argument("--database-path", default=str(DEFAULT_DATABASE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Elimina sólo la SQLite indicada antes de crear el seed.",
    )
    args = parser.parse_args(argv)

    database_path = Path(args.database_path)
    if database_path.parent != Path("."):
        database_path.parent.mkdir(parents=True, exist_ok=True)
    if args.reset and database_path.exists():
        database_path.unlink()

    database = SqliteDatabase(database_path, pragmas={"foreign_keys": 1})
    try:
        result = seed_controlled_audit_demo(
            database,
            username=args.username,
            password=args.password,
            output_dir=args.output_dir,
        )
    finally:
        if not database.is_closed():
            database.close()

    _print_summary(result, database_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

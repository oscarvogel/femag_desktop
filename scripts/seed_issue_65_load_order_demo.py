import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService


def _create_user(username: str, password: str) -> None:
    if User.get_or_none(User.username == username):
        return
    AuthService().create_user(username, password, "Administrador")


def _create_demo_order(username: str, run_id: str):
    carrier = Carrier.create(name=f"ISSUE65 Transporte Demo {run_id}", cuit=f"3070{run_id[-7:]}")
    driver = Driver.create(name=f"ISSUE65 Chofer Demo {run_id}", carrier=carrier, document=f"D{run_id[-7:]}")
    truck = Truck.create(domain=f"I65{run_id[-4:]}", carrier=carrier)
    client_a = Client.create(name=f"ISSUE65 Cliente Norte {run_id}", cuit=f"3065{run_id[-7:]}", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta 12 demo {run_id}",
        is_primary=True,
    )
    client_b = Client.create(name=f"ISSUE65 Cliente Sur {run_id}", cuit=f"3066{run_id[-7:]}", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address=f"Ruta 14 demo {run_id}",
        is_primary=True,
    )
    product_a = Product.create(name=f"ISSUE65 Fecula demo {run_id}", unit="kg")
    product_b = Product.create(name=f"ISSUE65 Almidon demo {run_id}", unit="bolsa")
    PalletType.get_or_create(type=f"ISSUE65 Pallet demo {run_id}", defaults={"measure": "1x1", "weight": 12.5})
    return LoadOrderService(current_user=username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client_a,
                "delivery_address": address_a,
                "products": [
                    {"product": product_a, "quantity": 1000, "observations": "Primer destino demo"},
                    {"product": product_b, "quantity": 20, "observations": "Segundo producto mismo cliente"},
                ],
            },
            {
                "client": client_b,
                "delivery_address": address_b,
                "products": [{"product": product_b, "quantity": 35, "observations": "Destino demo adicional"}],
            },
        ],
        pallets=[],
        observations=f"Orden demo issue #65 creada el {date.today():%d/%m/%Y}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo data for issue #65 multi-client load orders.")
    parser.add_argument("--username", default="issue65_demo")
    parser.add_argument("--password", default="demo")
    parser.add_argument("--prints-dir", default="outputs/load_orders/issue_65_demo")
    args = parser.parse_args()

    run_id = datetime.now().strftime("%y%m%d%H%M%S")
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    ensure_runtime_schema(db)
    PermissionService().seed_defaults()
    _create_user(args.username, args.password)
    order = _create_demo_order(args.username, run_id)
    output_dir = Path(args.prints_dir)
    combined = LoadOrderPrintService(current_user=args.username).export_combined(order, output_dir)

    print("Demo issue #65 creada")
    print(f"Usuario: {args.username}")
    print(f"Clave: {args.password}")
    print(f"Orden: OC-{order.order_number:06d}")
    print(f"Clientes/destinos: {order.destinations.count()}")
    print(f"Productos: {order.products.count()}")
    print(f"PDF A4: {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

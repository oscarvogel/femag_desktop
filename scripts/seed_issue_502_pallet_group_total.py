import sys
from pathlib import Path

from peewee import SqliteDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService


OUTPUT_DIR = Path("outputs") / "issue_502"
DATABASE_PATH = OUTPUT_DIR / "femag_issue_502.sqlite3"


def _create_case(*, username: str, pallet_count: int, quantity_per_pallet: int):
    carrier = Carrier.create(name=f"ISSUE502 Transporte {pallet_count}")
    driver = Driver.create(name=f"ISSUE502 Chofer {pallet_count}", carrier=carrier)
    truck = Truck.create(domain=f"I502{pallet_count:02d}", carrier=carrier)

    client = Client.create(
        name=f"ISSUE502 Cliente {pallet_count} pallets",
        cuit=f"3050200{pallet_count:04d}",
        iva_condition="RI",
        lista_precios=1,
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Puerto Rico",
        address=f"Destino prueba {pallet_count} pallets",
        is_primary=True,
    )

    iva = TipoIVA.iva_default()
    product = Product.create(
        name=f"ISSUE502 BOLSAS DE FECULA NATIVA {pallet_count}",
        unit="UNIDAD",
        peso_unitario_kg=25,
        product_kind="producto",
        classification_source="manual",
        weight_source="manual",
        review_required=False,
        precio_neto_base=1,
        precio_lista_1=1,
        precio_lista_2=1,
        precio_lista_3=1,
        precio_lista_4=1,
        tipo_iva=iva,
    )

    pallets = []
    for sequence in range(1, pallet_count + 1):
        pallets.append(
            {
                "sequence": sequence,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": product,
                        "quantity": quantity_per_pallet,
                    }
                ],
            }
        )

    return LoadOrderService(current_user=username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [
                    {
                        "product": product,
                        "quantity": pallet_count * quantity_per_pallet,
                    }
                ],
            }
        ],
        pallets=pallets,
        observations=(
            f"Issue #502: {pallet_count} pallets x {quantity_per_pallet} "
            f"= {pallet_count * quantity_per_pallet} unidades"
        ),
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()

    database = SqliteDatabase(DATABASE_PATH)
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    PermissionService().seed_defaults()

    username = "issue502_demo"
    printer = ConsolidatedLoadOrderPrintService(current_user=username)

    cases = [
        (19, 60),
        (2, 60),
    ]

    try:
        print("Seed visual issue #502")
        for pallet_count, quantity_per_pallet in cases:
            order = _create_case(
                username=username,
                pallet_count=pallet_count,
                quantity_per_pallet=quantity_per_pallet,
            )
            pdf = printer.export_pdf(order, OUTPUT_DIR)
            expected = pallet_count * quantity_per_pallet
            print(
                f"OC-{order.order_number:06d}: {pallet_count} pallets x "
                f"{quantity_per_pallet} = {expected} unidades -> {pdf}"
            )
    finally:
        database.close()

    print(f"DB aislada: {DATABASE_PATH}")
    print("Esperado en PDF:")
    print("  19 pallets -> 1140 UNIDADES")
    print("   2 pallets -> 120 UNIDADES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

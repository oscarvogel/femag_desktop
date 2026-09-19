from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderProduct,
    LoadOrderStatusHistory,
)
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    PalletType,
    Product,
    TipoIVA,
    Truck,
)
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from scripts.performance_mysql_common import (
    connect_performance_database,
    ensure_mysql_database,
    performance_db_config,
)


def _chunks(rows: list[dict], size: int = 1000):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _insert_many(model, rows: list[dict], *, chunk_size: int = 1000) -> None:
    for chunk in _chunks(rows, chunk_size):
        model.insert_many(chunk).execute()


def _seed_user() -> User:
    PermissionService().seed_defaults()
    existing = User.get_or_none(User.username == "performance")
    if existing is not None:
        return existing
    return AuthService().create_user("performance", "performance", "Administrador")


def seed_performance_data(order_count: int) -> dict[str, int]:
    if order_count < 1:
        raise ValueError("--orders debe ser mayor a cero.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = date.today()
    iva = TipoIVA.iva_default()
    _seed_user()

    client_count = max(20, min(500, max(1, order_count // 10)))
    product_count = 30
    carrier_count = 20

    clients = [
        Client.create(
            name=f"PERF Cliente {index + 1:04d}",
            cuit=f"30{700000000 + index:09d}",
            iva_condition="RI",
            phone=f"3764{100000 + index:06d}",
            lista_precios=(index % 4) + 1,
        )
        for index in range(client_count)
    ]
    addresses = [
        ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city=("Posadas", "Eldorado", "Puerto Rico", "Obera")[index % 4],
            address=f"Ruta performance {index + 1}",
            is_primary=True,
        )
        for index, client in enumerate(clients)
    ]

    products = [
        Product.create(
            codigo=f"PERF-{index + 1:03d}",
            name=f"PERF Producto {index + 1:03d}",
            unit="bolsa",
            peso_unitario_kg=25,
            product_kind="producto",
            classification_source="manual",
            weight_source="manual",
            review_required=False,
            precio_neto_base=10000 + index * 250,
            precio_lista_1=10000 + index * 250,
            precio_lista_2=10500 + index * 250,
            precio_lista_3=11000 + index * 250,
            precio_lista_4=11500 + index * 250,
            tipo_iva=iva,
        )
        for index in range(product_count)
    ]

    carriers = [
        Carrier.create(
            name=f"PERF Transporte {index + 1:02d}",
            cuit=f"30{800000000 + index:09d}",
        )
        for index in range(carrier_count)
    ]
    trucks = [
        Truck.create(
            domain=f"P{index + 1:02d}ERF",
            trailer_domain=f"T{index + 1:02d}ERF",
            carrier=carrier,
            max_load_kg=30000,
        )
        for index, carrier in enumerate(carriers)
    ]
    drivers = [
        Driver.create(
            name=f"PERF Chofer {index + 1:02d}",
            carrier=carrier,
            usual_truck=trucks[index],
            document=f"PERF-DNI-{index + 1:05d}",
            available=(index % 3 != 0),
        )
        for index, carrier in enumerate(carriers)
    ]
    pallet_type = PalletType.create(type="PERF Pallet", measure="1x1", weight=15)

    statuses = (
        LoadOrder.STATUS_PENDING,
        LoadOrder.STATUS_ISSUED,
        LoadOrder.STATUS_CLOSED,
        LoadOrder.STATUS_ANNULLED,
    )
    order_rows = []
    for index in range(order_count):
        carrier_index = index % carrier_count
        client_index = index % client_count
        order_rows.append(
            {
                "order_number": index + 1,
                "date": today - timedelta(days=index % 365),
                "client": clients[client_index].id,
                "delivery_address": addresses[client_index].id,
                "carrier": carriers[carrier_index].id,
                "driver": drivers[carrier_index].id,
                "truck": trucks[carrier_index].id,
                "trailer_domain": trucks[carrier_index].trailer_domain,
                "status": statuses[index % len(statuses)],
                "observations": f"Seed performance #{index + 1}",
                "created_by": "performance",
                "updated_by": "performance",
                "created_at": now,
                "updated_at": now,
            }
        )
    _insert_many(LoadOrder, order_rows)

    persisted_orders = list(
        LoadOrder.select(LoadOrder.id, LoadOrder.order_number).order_by(LoadOrder.order_number)
    )
    order_id_by_number = {row.order_number: row.id for row in persisted_orders}

    destination_rows = []
    for index in range(order_count):
        client_index = index % client_count
        destination_rows.append(
            {
                "order": order_id_by_number[index + 1],
                "client": clients[client_index].id,
                "delivery_address": addresses[client_index].id,
                "sequence": 1,
                "observations": "Destino principal performance",
                "created_at": now,
                "updated_at": now,
            }
        )
    _insert_many(LoadOrderDestination, destination_rows)

    persisted_destinations = list(
        LoadOrderDestination.select(LoadOrderDestination.id, LoadOrderDestination.order)
    )
    destination_id_by_order = {
        row.order_id: row.id for row in persisted_destinations
    }

    product_rows = []
    history_rows = []
    pallet_rows = []
    for index in range(order_count):
        order_id = order_id_by_number[index + 1]
        destination_id = destination_id_by_order[order_id]
        line_count = 2 if index % 3 == 0 else 1
        for offset in range(line_count):
            product = products[(index + offset) % product_count]
            quantity = 40 + ((index + offset) % 60)
            net = float(product.precio_lista_1) * quantity
            vat = round(net * 0.21, 2)
            product_rows.append(
                {
                    "order": order_id,
                    "destination": destination_id,
                    "product": product.id,
                    "quantity": quantity,
                    "unit": product.unit,
                    "observations": "Linea seed performance",
                    "precio_neto_unitario": float(product.precio_lista_1),
                    "neto_subtotal": net,
                    "neto_gravado": net,
                    "iva_porcentaje": 21.0,
                    "iva_importe": vat,
                    "total": net + vat,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        status = statuses[index % len(statuses)]
        history_rows.append(
            {
                "order": order_id,
                "old_status": None,
                "new_status": status,
                "user": "performance",
                "observation": "Seed performance",
                "created_at": now,
                "updated_at": now,
            }
        )
        if index % 2 == 0:
            pallet_rows.append(
                {
                    "order": order_id,
                    "pallet_type": pallet_type.id,
                    "sequence": 1,
                    "measure": pallet_type.measure,
                    "weight": pallet_type.weight,
                    "quantity": 1,
                    "observations": "Pallet seed performance",
                    "created_at": now,
                    "updated_at": now,
                }
            )

    _insert_many(LoadOrderProduct, product_rows)
    _insert_many(LoadOrderStatusHistory, history_rows)
    _insert_many(LoadOrderPallet, pallet_rows)

    return {
        "orders": order_count,
        "clients": client_count,
        "products": product_count,
        "carriers": carrier_count,
        "destinations": len(destination_rows),
        "order_products": len(product_rows),
        "pallets": len(pallet_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed MySQL aislado para benchmark FEMAG.")
    parser.add_argument("--orders", type=int, default=1000)
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra y recrea la DB de performance. Requerido para generar un seed limpio.",
    )
    args = parser.parse_args()

    if not args.reset:
        parser.error("Para sembrar datos debe indicar --reset explicitamente.")

    config = performance_db_config(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        database=args.db_name,
    )
    print(f"DB performance: {config.user}@{config.host}:{config.port}/{config.database}")
    print("RESET explicito habilitado: se borrara unicamente la DB de performance.")
    ensure_mysql_database(config, reset=True)
    database = connect_performance_database(config)
    try:
        started = time.perf_counter()
        counts = seed_performance_data(args.orders)
        elapsed = time.perf_counter() - started
        print("Seed completado.")
        for key, value in counts.items():
            print(f"  {key}: {value}")
        print(f"Tiempo seed: {elapsed:.2f} s")
        print("Usuario UI: performance")
        print("Clave UI: performance")
    finally:
        if not database.is_closed():
            database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

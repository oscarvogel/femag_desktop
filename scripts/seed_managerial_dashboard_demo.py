from __future__ import annotations

import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_demo_database
from app.config.schema import ensure_runtime_schema
from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import (
    CLIENT_ADDRESS_TYPE_DELIVERY,
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    TipoIVA,
    Truck,
)

ORDER_NUMBER_BASE = 990000
ORDER_NUMBER_LIMIT = 991000
SOURCE_PREFIX = "managerial-demo:"


def _month_start(reference: date, months_back: int) -> date:
    month_index = reference.year * 12 + (reference.month - 1) - months_back
    year, zero_based_month = divmod(month_index, 12)
    return date(year, zero_based_month + 1, 1)


def _date_in_month(month_start: date, preferred_day: int) -> date:
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return month_start.replace(day=min(preferred_day, last_day))


def _ensure_client(index: int, name: str, city: str, payment_days: int) -> tuple[Client, ClientAddress]:
    cuit = f"3099000000{index}"
    client, _ = Client.get_or_create(
        cuit=cuit,
        defaults={
            "name": name,
            "iva_condition": "RI",
            "contact": f"Contacto {name}",
            "active": True,
            "lista_precios": 1,
            "dias_plazo_pago": payment_days,
        },
    )
    client.name = name
    client.active = True
    client.dias_plazo_pago = payment_days
    client.save()
    address, _ = ClientAddress.get_or_create(
        client=client,
        address_type=CLIENT_ADDRESS_TYPE_DELIVERY,
        province="Misiones",
        city=city,
        address=f"Acceso {city} - Demo gerencial",
        defaults={"is_primary": True, "active": True},
    )
    address.active = True
    address.save()
    return client, address


def _ensure_product(code: str, name: str, weight_kg: float, price: float) -> Product:
    iva = TipoIVA.iva_default()
    product, _ = Product.get_or_create(
        name=name,
        defaults={
            "codigo": code,
            "unit": "bolsa",
            "peso_unitario_kg": weight_kg,
            "review_required": False,
            "active": True,
            "precio_neto_base": price,
            "precio_lista_1": price,
            "tipo_iva": iva,
        },
    )
    product.codigo = code
    product.unit = "bolsa"
    product.peso_unitario_kg = weight_kg
    product.review_required = False
    product.active = True
    product.precio_neto_base = price
    product.precio_lista_1 = price
    product.tipo_iva = iva
    product.save()
    return product


def _cleanup_previous_seed() -> None:
    ClientAccountMovement.delete().where(
        ClientAccountMovement.source_ref.startswith(SOURCE_PREFIX)
    ).execute()
    LoadOrder.delete().where(
        (LoadOrder.order_number >= ORDER_NUMBER_BASE)
        & (LoadOrder.order_number < ORDER_NUMBER_LIMIT)
    ).execute()


def _create_order(
    *,
    number: int,
    order_date: date,
    status: str,
    client: Client,
    address: ClientAddress,
    carrier: Carrier,
    driver: Driver,
    truck: Truck,
    lines: list[tuple[Product, float, float]],
) -> float:
    order = LoadOrder.create(
        order_number=number,
        date=order_date,
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=status,
        observations="Datos demo para validación visual del Dashboard Gerencial",
        created_by="demo",
        updated_by="demo",
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=client,
        delivery_address=address,
        sequence=1,
        observations="Destino demo gerencial",
    )
    order_total = 0.0
    for product, quantity, unit_price in lines:
        net = round(quantity * unit_price, 2)
        vat = round(net * 0.21, 2)
        total = round(net + vat, 2)
        LoadOrderProduct.create(
            order=order,
            destination=destination,
            product=product,
            quantity=quantity,
            unit=product.unit,
            precio_neto_unitario=unit_price,
            neto_subtotal=net,
            neto_gravado=net,
            iva_porcentaje=21.0,
            iva_importe=vat,
            total=total,
            observations="Línea demo gerencial",
        )
        order_total += total

    if status == LoadOrder.STATUS_CLOSED:
        due_date = order_date + timedelta(days=max(client.dias_plazo_pago, 0))
        ClientAccountMovement.create(
            client=client,
            load_order=order,
            movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
            amount=round(order_total / 1.21, 2),
            net_amount=round(order_total / 1.21, 2),
            vat_amount=round(order_total - (order_total / 1.21), 2),
            total_amount=round(order_total, 2),
            currency="ARS",
            movement_date=order_date,
            due_date=due_date,
            description=f"Despacho demo OC {number}",
            source_ref=f"{SOURCE_PREFIX}order:{number}",
            reference=str(number),
            created_by="demo",
        )
    return round(order_total, 2)


def main() -> int:
    database = initialize_demo_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)

    # Ensure the standard demo masters are present first.
    from app.ui.desktop_app import _seed_demo_masters

    _seed_demo_masters()
    _cleanup_previous_seed()

    carrier = Carrier.get_or_none(Carrier.name == "Demo Transportes") or Carrier.select().first()
    driver = Driver.select().where(Driver.active == True).first()  # noqa: E712
    truck = Truck.select().where(Truck.active == True).first()  # noqa: E712
    if carrier is None or driver is None or truck is None:
        raise RuntimeError("El seed demo base no creó transportista, chofer y camión utilizables.")

    clients = [
        _ensure_client(1, "Supermercados Norte", "Posadas", 15),
        _ensure_client(2, "Distribuidora Paraná", "Eldorado", 30),
        _ensure_client(3, "Alimentos Guaraní", "Oberá", 20),
        _ensure_client(4, "Mayorista Ruta 12", "Puerto Rico", 10),
        _ensure_client(5, "Industrias del Litoral", "Apóstoles", 45),
    ]
    products = [
        _ensure_product("G-100", "Almidón de mandioca 25 kg", 25.0, 14200.0),
        _ensure_product("G-200", "Almidón de maíz 25 kg", 25.0, 15800.0),
        _ensure_product("G-300", "Fécula modificada 25 kg", 25.0, 18600.0),
        _ensure_product("G-400", "Premezcla industrial 20 kg", 20.0, 21100.0),
    ]

    today = date.today()
    next_number = ORDER_NUMBER_BASE
    closed_orders = 0
    closed_total = 0.0

    # Twelve months of closed dispatches. Quantities and client/product mix vary
    # intentionally so evolution and ranking charts have visible differences.
    for months_back in range(11, -1, -1):
        month = _month_start(today, months_back)
        for slot, preferred_day in enumerate((5, 12, 19)):
            order_date = _date_in_month(month, preferred_day)
            if order_date > today:
                continue
            client, address = clients[(months_back + slot) % len(clients)]
            product_a = products[(slot + months_back) % len(products)]
            product_b = products[(slot + months_back + 1) % len(products)]
            seasonal = 1.0 + ((11 - months_back) * 0.045)
            quantity_a = round((420 + slot * 135 + (months_back % 3) * 55) * seasonal, 0)
            quantity_b = round((160 + slot * 70) * seasonal, 0)
            total = _create_order(
                number=next_number,
                order_date=order_date,
                status=LoadOrder.STATUS_CLOSED,
                client=client,
                address=address,
                carrier=carrier,
                driver=driver,
                truck=truck,
                lines=[
                    (product_a, quantity_a, float(product_a.precio_lista_1)),
                    (product_b, quantity_b, float(product_b.precio_lista_1)),
                ],
            )
            next_number += 1
            closed_orders += 1
            closed_total += total

    # Current-period non-effective states make the status distribution meaningful
    # without contaminating the effective KPI, which only counts Cerrada.
    current_month = today.replace(day=1)
    for status, client_index, product_index, day in (
        (LoadOrder.STATUS_PENDING, 0, 0, 7),
        (LoadOrder.STATUS_ISSUED, 1, 1, 14),
        (LoadOrder.STATUS_ANNULLED, 2, 2, 21),
    ):
        order_date = _date_in_month(current_month, day)
        if order_date > today:
            order_date = today
        client, address = clients[client_index]
        product = products[product_index]
        _create_order(
            number=next_number,
            order_date=order_date,
            status=status,
            client=client,
            address=address,
            carrier=carrier,
            driver=driver,
            truck=truck,
            lines=[(product, 280 + client_index * 60, float(product.precio_lista_1))],
        )
        next_number += 1

    # Partial payments create a realistic receivables balance and keep part of
    # the older debt overdue for the corresponding dashboard cards.
    payment_ratios = (0.72, 0.58, 0.81, 0.64, 0.76)
    for index, (client, _address) in enumerate(clients):
        billed = (
            ClientAccountMovement.select()
            .where(
                ClientAccountMovement.client == client,
                ClientAccountMovement.source_ref.startswith(f"{SOURCE_PREFIX}order:"),
            )
        )
        billed_total = sum(float(row.total_amount) for row in billed)
        paid = round(billed_total * payment_ratios[index], 2)
        if paid <= 0:
            continue
        ClientAccountMovement.create(
            client=client,
            movement_type=ClientAccountMovement.TYPE_PAYMENT,
            amount=-paid,
            net_amount=-paid,
            total_amount=-paid,
            currency="ARS",
            movement_date=today - timedelta(days=3 + index),
            description="Cobro parcial demo para Dashboard Gerencial",
            source_ref=f"{SOURCE_PREFIX}payment:{client.id}",
            reference=f"DEMO-PAGO-{client.id}",
            created_by="demo",
        )

    print("Seed del Dashboard Gerencial completado.")
    print(f"Órdenes cerradas: {closed_orders}")
    print(f"Órdenes totales demo gerencial: {next_number - ORDER_NUMBER_BASE}")
    print(f"Despachos valorizados históricos: $ {closed_total:,.2f}")
    print("Incluye 12 meses, rankings, estados y saldos/vencidos.")
    print("Ejecutar: python -m app.main --demo-ui")
    database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

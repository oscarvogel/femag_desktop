"""Los despachos de ordenes FEMAG mueven el stock (#573).

El evento es la **emision** de la orden: es cuando sale el presupuesto y la
mercaderia se va de la planta. El cierre de entrega es un paso administrativo
posterior y no mueve el stock. Y anular una orden emitida devuelve la
mercaderia.
"""

from decimal import Decimal

import pytest

from app.models.masters import (
    PRODUCT_KIND_PRODUCT,
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.models.stock import StockMovement
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.stock_service import StockService


def _product(name="BOLSAS DE FECULA NATIVA", peso="25.000"):
    return Product.create(
        name=name, unit="unidad", precio_neto_base=1000,
        peso_unitario_kg=Decimal(peso), product_kind=PRODUCT_KIND_PRODUCT, active=True,
    )


def _orden(*, allocations):
    """Orden creada con las asignaciones que se le pasen, sin emitir.

    Los destinos se agrupan por cliente y domicilio: el servicio rechaza dos
    destinos iguales en la misma orden, asi que un mismo destino con dos
    productos tiene que ser un destino con dos renglones.
    """
    carrier = Carrier.create(name="Transporte despacho")
    driver = Driver.create(name="Chofer despacho", carrier=carrier)
    truck = Truck.create(domain="DES220", carrier=carrier)

    por_destino: dict[tuple[int, int], list[dict]] = {}
    for a in allocations:
        por_destino.setdefault((a["client"].id, a["address"].id), []).append(
            {"product": a["product"], "quantity": a["quantity"]}
        )
    destinos = [
        {
            "client": allocations[0]["client"],
            "delivery_address": a["address"],
            "products": productos,
        }
        for a in allocations[:1]
        for (cliente_id, domicilio_id), productos in por_destino.items()
        if (cliente_id, domicilio_id) == (a["client"].id, a["address"].id)
    ]

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=destinos,
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": a["client"],
                        "delivery_address": a["address"],
                        "product": a["product"],
                        "quantity": a["quantity"],
                    }
                    for a in allocations
                ],
            }
        ],
    )
    return order


def _escena():
    cliente = Client.create(name="Cliente despacho", cuit="30111111112", iva_condition="RI")
    domicilio = ClientAddress.create(
        client=cliente, address_type="entrega", province="Misiones",
        city="Posadas", address="Ruta 1",
    )
    producto = _product()
    return _orden(
        allocations=[{"client": cliente, "address": domicilio, "product": producto, "quantity": 40}]
    ), producto


def test_emitir_la_orden_descuenta_el_stock(db):
    """Emitir es el evento: 40 bolsas x 25 kg = 1.000 kg fuera de la planta."""
    order, producto = _escena()

    LoadOrderOperationService(current_user="admin").issue(order)

    saldo = StockService.balance_for(producto)
    assert saldo.balance_kg == Decimal("-1000.000")
    assert saldo.outbound_kg == Decimal("1000.000")


def test_crear_la_orden_no_mueve_el_stock(db):
    """Un borrador es una intencion: todavia no salio nada."""
    order, producto = _escena()

    assert order.status in ("Pendiente", "Borrador")
    assert StockMovement.select().count() == 0
    assert StockService.balance_for(producto).balance_kg == Decimal("0.000")


def test_emitir_dos_veces_no_descuenta_dos_veces(db):
    """La idempotencia la garantiza el indice unico del libro."""
    order, producto = _escena()
    servicio = LoadOrderOperationService(current_user="admin")

    servicio.issue(order)
    with pytest.raises(ValueError, match="ya esta emitida"):
        servicio.issue(order)

    assert StockMovement.select().count() == 1
    assert StockService.balance_for(producto).balance_kg == Decimal("-1000.000")


def test_anular_una_orden_emitida_devuelve_la_mercaderia(db):
    """La mercaderia nunca llego a salir, asi que el stock tiene que volver."""
    order, producto = _escena()
    servicio = LoadOrderOperationService(current_user="admin")
    servicio.issue(order)
    assert StockService.balance_for(producto).balance_kg == Decimal("-1000.000")

    servicio.annul(order, can_annul=True, reason="No salio el camion")

    assert StockService.balance_for(producto).balance_kg == Decimal("0.000")
    # Quedan los dos movimientos: la salida y su reversa. Nada se borra.
    assert StockMovement.select().count() == 2
    assert StockMovement.select().where(StockMovement.is_reversal == False).count() == 1
    assert StockMovement.select().where(StockMovement.is_reversal == True).count() == 1


def test_anular_una_orden_anulada_no_revierte_dos_veces(db):
    """La segunda anulacion no debe devolver la mercaderia otra vez."""
    order, producto = _escena()
    servicio = LoadOrderOperationService(current_user="admin")
    servicio.issue(order)
    servicio.annul(order, can_annul=True, reason="No salio")

    with pytest.raises(ValueError, match="ya esta anulada"):
        servicio.annul(order, can_annul=True, reason="Otra vez")

    assert StockMovement.select().count() == 2
    assert StockService.balance_for(producto).balance_kg == Decimal("0.000")


def test_anular_una_orden_nunca_emitida_no_toca_el_stock(db):
    """Anular un borrador no genera movimientos: nunca hubo salida que revertir."""
    order, producto = _escena()

    LoadOrderOperationService(current_user="admin").annul(
        order, can_annul=True, reason="Error de carga"
    )

    assert StockMovement.select().count() == 0
    assert StockService.balance_for(producto).balance_kg == Decimal("0.000")


def test_el_peso_es_la_copia_de_la_asignacion_y_no_el_del_maestro(db):
    """Si se corrige el peso del maestro despues, lo que salio no se reescribe."""
    order, producto = _escena()
    LoadOrderOperationService(current_user="admin").issue(order)

    producto.peso_unitario_kg = Decimal("30.000")
    producto.save()

    assert StockService.balance_for(producto).balance_kg == Decimal("-1000.000")


def test_un_producto_sin_peso_no_llega_ni_a_descontarse(db):
    """Sin peso de bolsa la orden ni siquiera se puede emitir.

    El descuento no tiene que defenderse de un producto sin peso porque la app
    no deja emitir una orden con ese producto. La guarda del servicio queda como
    red de seguridad, no como la unica linea de defensa.
    """
    cliente = Client.create(name="Cliente sin peso", cuit="30222222221", iva_condition="RI")
    domicilio = ClientAddress.create(
        client=cliente, address_type="entrega", province="Misiones",
        city="Obera", address="Ruta 2",
    )
    producto = _product("ALMIDON A GRANEL", "0")

    order = _orden(
        allocations=[{"client": cliente, "address": domicilio, "product": producto, "quantity": 10}]
    )
    with pytest.raises(ValueError, match="peso pendiente"):
        LoadOrderOperationService(current_user="admin").issue(order)

    assert StockMovement.select().count() == 0


def test_varios_productos_generan_un_movimiento_cada_uno(db):
    cliente = Client.create(name="Cliente dos productos", cuit="30333333332", iva_condition="RI")
    domicilio = ClientAddress.create(
        client=cliente, address_type="entrega", province="Misiones",
        city="Garupá", address="Ruta 3",
    )
    fecula = _product("BOLSAS DE FECULA NATIVA", "25.000")
    almidon = _product("BOLSAS ALMIDON DE MAIZ X 25 KG.", "25.000")
    order = _orden(
        allocations=[
            {"client": cliente, "address": domicilio, "product": fecula, "quantity": 40},
            {"client": cliente, "address": domicilio, "product": almidon, "quantity": 10},
        ]
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    assert StockMovement.select().count() == 2
    assert StockService.balance_for(fecula).balance_kg == Decimal("-1000.000")
    assert StockService.balance_for(almidon).balance_kg == Decimal("-250.000")

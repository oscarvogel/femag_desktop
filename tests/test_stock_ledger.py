from datetime import date
from decimal import Decimal

import pytest

from app.models.masters import Product
from app.models.stock import StockMovement
from app.services.stock_service import StockService

DAY = date(2026, 10, 1)
OTHER_DAY = date(2026, 10, 2)


def _product(name="Fecula de mandioca", weight="25.000"):
    return Product.create(
        name=name, unit="bolsa", peso_unitario_kg=Decimal(weight), active=True
    )


def test_movement_quantity_is_always_positive_and_the_type_gives_the_sign(db):
    """No puede existir un movimiento que se contradiga: cantidad positiva, direccion en el tipo."""
    product = _product()

    entrada = StockService.register(
        product=product,
        movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("750.5"),
        source_ref="production_part:1",
        description="Bolsas embolsadas del turno mañana",
        movement_date=DAY,
        created_by="operador",
    )
    salida = StockService.register(
        product=product,
        movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("250.25"),
        source_ref="load_order:9",
        description="Despacho de la orden 9",
        movement_date=DAY,
    )

    assert entrada.quantity_kg == Decimal("750.500")
    assert salida.quantity_kg == Decimal("250.250")
    assert entrada.signed_quantity_kg == Decimal("750.500")
    assert salida.signed_quantity_kg == Decimal("-250.250")


def test_registering_the_same_source_twice_does_not_duplicate(db):
    """Idempotencia: un documento no puede generar dos veces el mismo movimiento."""
    product = _product()
    argumentos = dict(
        product=product,
        movement_type=StockMovement.TYPE_PURCHASE,
        quantity_kg=Decimal("1000"),
        source_ref="compra:77",
        description="Compra a proveedor",
        movement_date=DAY,
    )

    primero = StockService.register(**argumentos)
    segundo = StockService.register(**argumentos)

    assert segundo.id == primero.id
    assert StockService.total_movements() == 1
    assert StockService.balance_for(product).balance_kg == Decimal("1000.000")


def test_balance_is_derived_from_movements_not_stored(db):
    product = _product()
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
        quantity_kg=Decimal("1000"), source_ref="inventario:2026-10-01",
        description="Inventario inicial", movement_date=DAY,
    )
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("750"), source_ref="production_part:1",
        description="Produccion del dia", movement_date=DAY,
    )
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("300"), source_ref="load_order:9",
        description="Despacho", movement_date=DAY,
    )

    saldo = StockService.balance_for(product)

    assert saldo.inbound_kg == Decimal("1750.000")
    assert saldo.outbound_kg == Decimal("300.000")
    assert saldo.balance_kg == Decimal("1450.000")
    assert saldo.movements == 3
    assert not saldo.is_negative


def test_balance_can_go_negative_and_says_so(db):
    """Un despacho mayor que lo disponible tiene que poder existir: el saldo avisa."""
    product = _product()
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("120"), source_ref="load_order:1",
        description="Despacho", movement_date=DAY,
    )

    saldo = StockService.balance_for(product)

    assert saldo.balance_kg == Decimal("-120.000")
    assert saldo.is_negative


def test_reverse_adds_the_opposite_movement_without_touching_the_original(db):
    """Corregir no reescribe: queda el original y aparece el contrario."""
    product = _product()
    original = StockService.register(
        product=product, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("500"), source_ref="production_part:1",
        description="Produccion", movement_date=DAY,
    )

    reversa = StockService.reverse(original, created_by="supervisor", reason="Se conto dos veces")

    assert reversa.movement_type == StockMovement.TYPE_ADJUSTMENT_NEGATIVE
    assert reversa.signed_quantity_kg == Decimal("-500.000")
    assert reversa.reverses_id == original.id
    assert reversa.observations == "Se conto dos veces"
    assert reversa.created_by == "supervisor"
    # El original sigue intacto.
    assert StockMovement.get_by_id(original.id).quantity_kg == Decimal("500.000")
    assert StockService.balance_for(product).balance_kg == Decimal("0.000")


def test_reverse_is_itself_idempotent(db):
    product = _product()
    original = StockService.register(
        product=product, movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("80"), source_ref="load_order:5",
        description="Despacho", movement_date=DAY,
    )

    primera = StockService.reverse(original, created_by="supervisor", reason="Error de carga")
    segunda = StockService.reverse(original, created_by="supervisor", reason="Error de carga")

    assert segunda.id == primera.id
    assert StockService.total_movements() == 2
    assert StockService.balance_for(product).balance_kg == Decimal("0.000")


def test_reverse_requires_a_reason_and_refuses_to_revert_a_reversal(db):
    product = _product()
    original = StockService.register(
        product=product, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("10"), source_ref="production_part:2",
        description="Produccion", movement_date=DAY,
    )

    with pytest.raises(ValueError, match="por qué"):
        StockService.reverse(original)

    reversa = StockService.reverse(original, reason="Correccion")
    with pytest.raises(ValueError, match="No se puede revertir una reversa"):
        StockService.reverse(reversa, reason="Otra correccion")


def test_balances_lists_every_product_with_movements(db):
    almidon = _product("Almidon de maiz", "25.000")
    fecula = _product("Fecula de mandioca", "25.000")
    StockService.register(
        product=almidon, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("100"), source_ref="production_part:1",
        description="Produccion", movement_date=DAY,
    )
    StockService.register(
        product=fecula, movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("40"), source_ref="load_order:1",
        description="Despacho", movement_date=DAY,
    )

    saldos = {saldo.product.id: saldo for saldo in StockService.balances()}

    assert set(saldos) == {almidon.id, fecula.id}
    assert saldos[almidon.id].balance_kg == Decimal("100.000")
    assert saldos[fecula.id].balance_kg == Decimal("-40.000")


def test_balance_until_a_date_ignores_later_movements(db):
    product = _product()
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("100"), source_ref="production_part:1",
        description="Produccion", movement_date=DAY,
    )
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_DISPATCH,
        quantity_kg=Decimal("30"), source_ref="load_order:1",
        description="Despacho", movement_date=OTHER_DAY,
    )

    assert StockService.balance_for(product, until=DAY).balance_kg == Decimal("100.000")
    assert StockService.balance_for(product).balance_kg == Decimal("70.000")


def test_product_without_movements_has_a_zero_balance(db):
    producto = _product()
    saldo = StockService.balance_for(producto)

    assert saldo.balance_kg == Decimal("0.000")
    assert saldo.movements == 0
    assert not saldo.is_negative


@pytest.mark.parametrize(
    "movimiento",
    ["cantidad_cero", "cantidad_negativa", "cantidad_texto", "tipo_invalido", "sin_origen", "sin_descripcion"],
)
def test_register_rejects_invalid_input(db, movimiento):
    product = _product()
    base = dict(
        product=product,
        movement_type=StockMovement.TYPE_ADJUSTMENT_POSITIVE,
        quantity_kg=Decimal("1"),
        source_ref="ajuste:1",
        description="Ajuste",
        movement_date=DAY,
    )
    if movimiento == "cantidad_cero":
        base["quantity_kg"] = Decimal("0")
    elif movimiento == "cantidad_negativa":
        base["quantity_kg"] = Decimal("-5")
    elif movimiento == "cantidad_texto":
        base["quantity_kg"] = "muchos"
    elif movimiento == "tipo_invalido":
        base["movement_type"] = "teletransporte"
    elif movimiento == "sin_origen":
        base["source_ref"] = "   "
    elif movimiento == "sin_descripcion":
        base["description"] = ""

    with pytest.raises(ValueError):
        StockService.register(**base)

    assert StockService.total_movements() == 0


def test_adjustment_types_move_the_balance_in_the_right_direction(db):
    """AJUSTE_POSITIVO suma y AJUSTE_NEGATIVO resta: el tipo manda."""
    product = _product()
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_IMPORT,
        quantity_kg=Decimal("100"), source_ref="importacion:1",
        description="Importacion", movement_date=DAY,
    )
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_ADJUSTMENT_POSITIVE,
        quantity_kg=Decimal("7"), source_ref="ajuste:1",
        description="Ajuste por conteo", movement_date=DAY,
    )
    StockService.register(
        product=product, movement_type=StockMovement.TYPE_ADJUSTMENT_NEGATIVE,
        quantity_kg=Decimal("3"), source_ref="ajuste:2",
        description="Ajuste por merma", movement_date=DAY,
    )

    assert StockService.balance_for(product).balance_kg == Decimal("104.000")


def test_balance_sums_decimal_quantities_without_float_math(db):
    """Los kg se acumulan con Decimal, no con float.

    Ojo con el limite de SQLite: su afinidad NUMERIC guarda 0.1 como REAL, asi
    que la suma de tres 0.1 no da exactamente 0.300 en los tests. Contra MySQL,
    que si usa DECIMAL de verdad, la suma es exacta y eso se verifica en la
    validacion contra la base real. Aca se controla que la desviacion sea del
    orden del punto flotante y no de un bug de signo o de unidad.
    """
    product = _product()
    for indice in range(3):
        StockService.register(
            product=product, movement_type=StockMovement.TYPE_PRODUCTION,
            quantity_kg=Decimal("0.1"), source_ref=f"production_part:{indice}",
            description="Produccion", movement_date=DAY,
        )

    saldo = StockService.balance_for(product)

    assert abs(saldo.balance_kg - Decimal("0.300")) < Decimal("0.000001")
    assert saldo.movements == 3


def test_quantities_are_stored_with_three_decimals(db):
    """La cantidad se guarda quantizada a 3 decimales, no con la precision que mande."""
    product = _product()
    movimiento = StockService.register(
        product=product, movement_type=StockMovement.TYPE_PRODUCTION,
        quantity_kg=Decimal("750.50049"), source_ref="production_part:1",
        description="Produccion", movement_date=DAY,
    )

    assert movimiento.quantity_kg == Decimal("750.500")

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from peewee import fn

from app.models.masters import Product
from app.models.stock import StockMovement

THREE_PLACES = Decimal("0.001")
ZERO = Decimal("0.000")


@dataclass(frozen=True)
class StockBalance:
    """Saldo derivado de los movimientos de un producto."""

    product: Product
    inbound_kg: Decimal
    outbound_kg: Decimal
    balance_kg: Decimal
    movements: int

    @property
    def is_negative(self) -> bool:
        return self.balance_kg < ZERO


def _tipo_a_saldo(movement_type: str) -> int:
    return -1 if movement_type in StockMovement.OUTBOUND_TYPES else 1


def bag_weight_of(product) -> Decimal:
    """Peso de bolsa del producto, o cero si no tiene cargado.

    El conteo fisico se hace en bolsas y los kilos salen de multiplicar por
    este peso, asi que la conversion vive aca y no en cada pantalla.
    """
    if product is None:
        return ZERO
    return Decimal(str(product.peso_unitario_kg or 0))


def is_countable_in_bags(product) -> bool:
    """Si el producto se puede contar en bolsas.

    Sin peso de bolsa cargado, N bolsas darian 0 kg: la diferencia contra el
    libro seria -saldo y el conteo generaria un ajuste que deja el producto en
    cero. Por eso el peso es obligatorio para contar, no una convenience.
    """
    if product is None or getattr(product, "id", None) is None:
        return False
    return bag_weight_of(product) > ZERO


def bags_to_kg(product, bags) -> Decimal:
    """Convierte bolsas a kilos con el peso del producto.

    Devuelve cero si el producto no tiene peso cargado. Quien llame tiene que
    haber comprobado :func:`is_countable_in_bags` antes: convertir a la fuerza
    un producto sin peso es justamente lo que produce el ajuste que borra el
    saldo.
    """
    try:
        unidades = Decimal(str(bags or 0))
    except (TypeError, ValueError, ArithmeticError):
        return ZERO
    return (unidades * bag_weight_of(product)).quantize(Decimal("0.001"))


class StockService:
    """Libro auditable de movimientos de stock (#572).

    No existe un campo de stock mutable: el saldo se deriva sumando los
    movimientos. Registrar es idempotente por ``source_ref`` y la correccion de
    un movimiento genera el contrario en vez de reescribir el original.
    """

    @staticmethod
    def _quantity(raw) -> Decimal:
        try:
            quantity = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("La cantidad de stock debe ser un número.") from None
        if not quantity.is_finite():
            raise ValueError("La cantidad de stock debe ser un número.")
        quantity = quantity.quantize(THREE_PLACES, rounding=ROUND_HALF_UP)
        if quantity <= ZERO:
            raise ValueError("La cantidad de stock debe ser mayor a cero.")
        return quantity

    @staticmethod
    def _values(*, product, movement_type: str, source_ref: str, description: str):
        if product is None:
            raise ValueError("Cada movimiento necesita un producto.")
        if movement_type not in StockMovement.ALL_TYPES:
            raise ValueError(f"El tipo de movimiento '{movement_type}' no es válido.")
        source_ref = (source_ref or "").strip()
        if not source_ref:
            raise ValueError("El movimiento necesita un origen (source_ref).")
        description = (description or "").strip()
        if not description:
            raise ValueError("El movimiento necesita una descripción.")
        return source_ref, description

    @staticmethod
    def find_by_source(product, source_ref: str, movement_type: str, *, is_reversal: bool = False):
        return (
            StockMovement.select()
            .where(
                (StockMovement.product == product)
                & (StockMovement.source_ref == source_ref)
                & (StockMovement.movement_type == movement_type)
                & (StockMovement.is_reversal == is_reversal)
            )
            .order_by(StockMovement.id)
            .first()
        )

    @classmethod
    def register(
        cls,
        *,
        product,
        movement_type: str,
        quantity_kg,
        source_ref: str,
        description: str,
        movement_date: date | None = None,
        observations: str | None = None,
        created_by: str | None = None,
        reverses: StockMovement | None = None,
    ) -> StockMovement:
        """Registra un movimiento. Repetir el mismo origen no duplica nada.

        Si ya existe un movimiento igual (mismo origen, producto, tipo y sin ser
        reversa) devuelve el existente en lugar de crear otro. Es lo que evita
        que un documento se descuente dos veces.
        """
        source_ref, description = cls._values(
            product=product, movement_type=movement_type, source_ref=source_ref,
            description=description,
        )
        quantity = cls._quantity(quantity_kg)

        existente = cls.find_by_source(product, source_ref, movement_type)
        if existente is not None:
            return existente

        with StockMovement._meta.database.atomic():
            # Se vuelve a consultar dentro de la transaccion: dos procesos que
            # registran el mismo origen a la vez no deben pasar los dos.
            existente = cls.find_by_source(product, source_ref, movement_type)
            if existente is not None:
                return existente
            movimiento = StockMovement.create(
                product=product,
                movement_type=movement_type,
                quantity_kg=quantity,
                movement_date=movement_date,
                source_ref=source_ref,
                description=description,
                observations=(observations or "").strip() or None,
                created_by=(created_by or "").strip() or None,
            )
            if reverses is not None:
                # El vinculo se escribe despues de crear porque el self-FK
                # necesita el id del movimiento al que corrige.
                movimiento.reverses = reverses
                movimiento.is_reversal = True
                movimiento.save()
            return movimiento

    @classmethod
    def reverse(
        cls, movement: StockMovement, *, created_by: str | None = None, reason: str = ""
    ) -> StockMovement:
        """Corrige un movimiento agregando el contrario.

        No borra ni edita el original: ambos quedan en el libro y el nuevo
        apunta al que corrige. Es la unica forma de mantener la trazabilidad
        que pide #574.
        """
        if movement.is_reversal:
            raise ValueError("No se puede revertir una reversa: corregí el movimiento original.")

        contrario = (
            StockMovement.TYPE_ADJUSTMENT_NEGATIVE
            if movement.is_inbound
            else StockMovement.TYPE_ADJUSTMENT_POSITIVE
        )
        observaciones = (reason or "").strip()
        if not observaciones:
            raise ValueError("Explicá por qué se corrige el movimiento.")

        # La idempotencia de la reversa es por movimiento corregido, no por
        # origen: un mismo documento puede tener varias correcciones, pero de
        # cada movimiento original hay a lo sumo una reversa vigente.
        ya_revertido = StockMovement.get_or_none(
            (StockMovement.reverses == movement)
            & (StockMovement.movement_type == contrario)
        )
        if ya_revertido is not None:
            return ya_revertido

        return cls.register(
            product=movement.product,
            movement_type=contrario,
            quantity_kg=movement.quantity_kg,
            source_ref=movement.source_ref,
            description=f"Anulación de {movement.description}",
            movement_date=movement.movement_date,
            observations=observaciones,
            created_by=created_by,
            reverses=movement,
        )

    @staticmethod
    def _base_query(until: date | None = None):
        query = StockMovement.select()
        if until is not None:
            query = query.where(StockMovement.movement_date <= until)
        return query

    @classmethod
    def movements_for(cls, product, *, until: date | None = None):
        return list(
            cls._base_query(until)
            .where(StockMovement.product == product)
            .order_by(StockMovement.id)
        )

    @classmethod
    def _totals_por_tipo(cls, product_ids, until: date | None):
        """Suma de kg por producto, separando entradas y salidas.

        Se suman columnas DECIMAL puras, sin multiplicar por un signo: en SQLite
        ``SUM(cantidad * CASE ...)`` devuelve float y ``0.1 + 0.2`` deja de ser
        exacto, que es justo lo que un saldo en kg no puede permitirse. El signo
        se aplica despues, en Python y con Decimal.
        """
        totales: dict[int, dict[str, Decimal]] = {}
        for tipos, clave in (
            (StockMovement.INBOUND_TYPES, "inbound_kg"),
            (StockMovement.OUTBOUND_TYPES, "outbound_kg"),
        ):
            consulta = (
                StockMovement.select(
                    StockMovement.product,
                    fn.SUM(StockMovement.quantity_kg).alias("kg"),
                )
                .where(StockMovement.movement_type.in_(sorted(tipos)))
                .group_by(StockMovement.product)
            )
            if product_ids is not None:
                consulta = consulta.where(StockMovement.product << list(product_ids))
            if until is not None:
                consulta = consulta.where(StockMovement.movement_date <= until)
            for fila in consulta.dicts():
                producto = fila["product"]
                entrada = totales.setdefault(producto, {"inbound_kg": ZERO, "outbound_kg": ZERO})
                entrada[clave] += Decimal(str(fila["kg"] or 0))
        return totales

    @classmethod
    def _conteo_por_producto(cls, product_ids, until: date | None) -> dict[int, int]:
        consulta = StockMovement.select(
            StockMovement.product, fn.COUNT(StockMovement.id).alias("movimientos")
        ).group_by(StockMovement.product)
        if product_ids is not None:
            consulta = consulta.where(StockMovement.product << list(product_ids))
        if until is not None:
            consulta = consulta.where(StockMovement.movement_date <= until)
        return {fila["product"]: int(fila["movimientos"] or 0) for fila in consulta.dicts()}

    @classmethod
    def balance_for(cls, product, *, until: date | None = None) -> StockBalance:
        if product is None:
            raise ValueError("Indicá el producto del saldo.")
        totales = cls._totals_por_tipo([product.id], until).get(
            product.id, {"inbound_kg": ZERO, "outbound_kg": ZERO}
        )
        movimientos = cls._conteo_por_producto([product.id], until).get(product.id, 0)
        return StockBalance(
            product=product,
            inbound_kg=totales["inbound_kg"],
            outbound_kg=totales["outbound_kg"],
            balance_kg=totales["inbound_kg"] - totales["outbound_kg"],
            movements=movimientos,
        )

    @classmethod
    def balances(cls, *, until: date | None = None) -> list[StockBalance]:
        """Saldos de todos los productos con movimientos."""
        totales = cls._totals_por_tipo(None, until)
        if not totales:
            return []
        conteos = cls._conteo_por_producto(None, until)
        productos = {
            producto.id: producto
            for producto in Product.select().where(Product.id << list(totales))
        }
        resultado = []
        for producto_id, cifras in totales.items():
            producto = productos.get(producto_id)
            if producto is None:  # pragma: no cover - producto borrado a mano.
                continue
            resultado.append(
                StockBalance(
                    product=producto,
                    inbound_kg=cifras["inbound_kg"],
                    outbound_kg=cifras["outbound_kg"],
                    balance_kg=cifras["inbound_kg"] - cifras["outbound_kg"],
                    movements=conteos.get(producto_id, 0),
                )
            )
        return resultado

    @staticmethod
    def total_movements() -> int:
        return StockMovement.select().count()
